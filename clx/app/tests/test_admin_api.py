import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.test import Client

from clx.app.models import User
from clx.app.permissions import GROUPS, PERMISSIONS
from clx.app.selectors.site_config import site_config_get
from clx.app.selectors.user import USER_LEVELS, user_level
from clx.app.services.user import LEVEL_GROUPS, user_create


@pytest.mark.django_db
def test_settings_update_changes_the_site_name(admin_user: User) -> None:
    """The endpoint is the settings page's save button: it hands the body to
    site_config_update, so the row changes and the cached copy every page
    context reads is busted. This fails if the endpoint stops calling the
    service, or if the service stops busting the cache — either way the old
    name would keep rendering until the TTL expired.
    """
    client = Client()
    client.force_login(admin_user)

    response = client.post(
        "/api/admin/settings/",
        '{"site_name": "  Acme  "}',
        content_type="application/json",
        secure=True,
    )

    assert response.status_code == 200
    assert response.json() == {"site_name": "Acme"}
    assert site_config_get().site_name == "Acme"


@pytest.mark.django_db
def test_settings_update_requires_the_admin_permission() -> None:
    """Hiding the admin tab is cosmetic; the endpoint is the guard. A signed-in
    user without app.manage_admin gets the 403 JSON shape, and the config is
    untouched. This fails if perms= is dropped from the endpoint's api_auth.
    """
    user = user_create(email="regular@example.com")
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/admin/settings/",
        '{"site_name": "Hijacked"}',
        content_type="application/json",
        secure=True,
    )

    assert response.status_code == 403
    assert site_config_get().site_name == "CLX"

    anonymous = Client().post(
        "/api/admin/settings/",
        '{"site_name": "Hijacked"}',
        content_type="application/json",
        secure=True,
    )
    assert anonymous.status_code == 401


@pytest.mark.django_db
def test_settings_update_rejects_a_blank_site_name(admin_user: User) -> None:
    """site_name is required by the model, and full_clean runs in the service,
    so a blank name comes back as the middleware's 400 shape with the field
    named in extra — the settings form shows that message instead of saving
    an empty wordmark.
    """
    client = Client()
    client.force_login(admin_user)

    response = client.post(
        "/api/admin/settings/",
        '{"site_name": "   "}',
        content_type="application/json",
        secure=True,
    )

    assert response.status_code == 400
    assert "site_name" in response.json()["extra"]["fields"]
    assert site_config_get().site_name == "CLX"


@pytest.mark.django_db
def test_user_list_marks_what_the_caller_may_edit(admin_user: User) -> None:
    """The list endpoint precomputes the segmented control's state — level,
    editability, and the caller's ceiling — so the page never re-derives
    permission rules in JavaScript. For an admin caller: their own row and
    any developer's row are locked, a basic row is editable, and max_level
    "admin" tells the client the developer segment is off the table. A
    caller without app.manage_admin never sees the list at all.
    """
    user_create(email="a-basic@example.com")
    developer = user_create(email="a-developer@example.com")
    developer.groups.add(Group.objects.get(name="Developer"))

    client = Client()
    client.force_login(admin_user)
    response = client.get("/api/admin/users/", secure=True)

    assert response.status_code == 200
    data = response.json()
    assert data["max_level"] == "admin"
    rows = {row["email"]: row for row in data["users"]}
    assert rows["admin@example.com"]["self"] is True
    assert rows["admin@example.com"]["editable"] is False
    assert rows["a-basic@example.com"]["editable"] is True
    assert rows["a-developer@example.com"]["level"] == "developer"
    assert rows["a-developer@example.com"]["editable"] is False

    regular = Client()
    regular.force_login(user_create(email="a-nobody@example.com"))
    assert regular.get("/api/admin/users/", secure=True).status_code == 403


@pytest.mark.django_db
def test_user_list_search_and_pagination_pass_through(
    admin_user: User,
) -> None:
    """search and page are the endpoint's only inputs; both reach the
    selector. A search that matches one user returns exactly that row, and
    a nonsense page clamps instead of erroring, because the page footer's
    next/prev math trusts what the server reports.
    """
    user_create(email="findme@example.com")

    client = Client()
    client.force_login(admin_user)

    found = client.get(
        "/api/admin/users/?search=findme&page=999", secure=True
    ).json()
    assert [row["email"] for row in found["users"]] == ["findme@example.com"]
    assert found["page"] == 1


@pytest.mark.django_db
def test_user_level_update_enforces_the_service_rules(
    admin_user: User,
) -> None:
    """The endpoint is a thin wrapper over user_level_set, so the ladder
    rules surface as the middleware's 400 shape: an admin promoting a basic
    user succeeds, granting developer fails, and self-service fails. The
    row's new level comes back so the client could patch in place.
    """
    target = user_create(email="t-basic@example.com")
    client = Client()
    client.force_login(admin_user)

    promoted = client.post(
        "/api/admin/users/level/",
        f'{{"user_id": "{target.id}", "level": "admin"}}',
        content_type="application/json",
        secure=True,
    )
    assert promoted.status_code == 200
    assert promoted.json()["level"] == "admin"
    assert user_level(target) == "admin"

    escalate = client.post(
        "/api/admin/users/level/",
        f'{{"user_id": "{target.id}", "level": "developer"}}',
        content_type="application/json",
        secure=True,
    )
    assert escalate.status_code == 400
    assert user_level(target) == "admin"

    themselves = client.post(
        "/api/admin/users/level/",
        f'{{"user_id": "{admin_user.id}", "level": "basic"}}',
        content_type="application/json",
        secure=True,
    )
    assert themselves.status_code == 400
    assert user_level(admin_user) == "admin"


@pytest.mark.django_db
def test_the_users_page_tracks_the_permission_registry() -> None:
    """permissions.py is the registry; the users page is built on top of it
    through the level ladder. Each piece can silently drift when the
    registry grows, so each is pinned here:

    - Every level must map to registry groups and every group must be
      reachable through some level, or a new group (say, Support) could
      never be granted from the page.
    - A member of any registry group must rank above basic, or user_level
      would report them as Basic and the ladder rules would let an admin
      "manage" someone who actually outranks them.
    - Every permission must be granted by some group, or the right-panel
      breakdown (which renders group-by-group) would never show it.
    - The page's segmented control hard-codes the level names in its script
      block, so the template must mention every level.
    """
    assert set(LEVEL_GROUPS) == set(USER_LEVELS)
    reachable = {name for names in LEVEL_GROUPS.values() for name in names}
    assert reachable == set(GROUPS)

    for name in GROUPS:
        member = user_create(email=f"probe-{name.lower()}@example.com")
        member.groups.add(Group.objects.get(name=name))
        assert user_level(member) != "basic", name

    granted = {
        codename for codenames in GROUPS.values() for codename in codenames
    }
    assert granted == set(PERMISSIONS)

    template = (
        settings.BASE_DIR
        / "app"
        / "templates"
        / "pages"
        / "admin"
        / "users.html"
    ).read_text()
    for level in USER_LEVELS:
        assert f'"{level}"' in template, level
