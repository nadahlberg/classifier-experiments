from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.storage import Storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from clx.app.exceptions import ApplicationError
from clx.app.models import DemoUpload, User
from clx.app.selectors.user import (
    USERS_PER_PAGE,
    user_level,
    user_search,
)
from clx.app.services.demo import demo_upload_create_batch
from clx.app.services.user import user_create, user_level_set


@pytest.mark.django_db
def test_the_whole_address_is_lowercased_not_just_the_domain() -> None:
    """Django's BaseUserManager.normalize_email lowercases only the domain,
    because the RFC allows a case-sensitive local part.

    No mail provider actually treats "Foo@example.com" and "foo@example.com"
    as different mailboxes, so a user who types their address with different
    capitalisation on signup and on password reset would otherwise end up
    with two accounts. This fails if the local part is left alone.
    """
    user = user_create(email="Foo.Bar@Example.COM")

    assert user.email == "foo.bar@example.com"


@pytest.mark.django_db
def test_case_variants_of_one_address_cannot_both_be_registered() -> None:
    """Normalisation happens in clean(), which full_clean() runs before
    validate_unique(), so User.email's unique=True is checked against the
    normalised value.

    That is what makes the lowercasing worth anything: the second signup is
    rejected rather than quietly creating the duplicate account. This fails
    if normalisation moves after the uniqueness check, or into a layer that
    the second call does not go through.
    """
    user_create(email="foo@example.com")

    with pytest.raises(ValidationError):
        user_create(email="FOO@example.com")


@pytest.mark.django_db
def test_the_superuser_path_normalises_the_same_way() -> None:
    """createsuperuser goes through the manager, not through user_create.

    A superuser created as "Admin@Example.com" would be a mixed-case row
    that no later lookup by the normalised address can find — the same
    two-accounts bug, on the one account that matters most. This fails if
    create_user stops calling full_clean().
    """
    user = User.objects.create_superuser("Admin@Example.com", "password")

    assert user.email == "admin@example.com"


@pytest.mark.django_db
def test_a_missing_email_raises_an_application_error() -> None:
    """Every failure this codebase raises on purpose is an ApplicationError.

    ApiErrorMiddleware renders it as {"message", "extra"} with a 400 and the
    MCP ToolMiddleware turns it into a ToolError; a bare ValueError bypasses
    both and reaches the client as a 500. This fails if the guard goes back
    to raising ValueError.
    """
    with pytest.raises(ApplicationError):
        User.objects.create_user("")


@pytest.mark.django_db
@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
def test_create_superuser_refuses_to_drop_a_privilege_flag(
    flag: str,
) -> None:
    """setdefault only fills in a flag the caller omitted; an explicit False
    passes straight through.

    Without this guard create_superuser(..., is_superuser=False) returns an
    ordinary account to a caller who believes it is privileged. Django's own
    UserManager raises here, and so does ours. This fails if either check is
    dropped or the raise is replaced by another setdefault.
    """
    with pytest.raises(ApplicationError):
        User.objects.create_superuser(
            "admin@example.com", "password", **{flag: False}
        )


@pytest.mark.django_db
def test_profile_endpoint_updates_names_for_the_caller_only() -> None:
    """The me endpoint always acts on request.user — there is no user id in
    the request to tamper with — and it trims whitespace through the
    service. Anonymous callers get the standard 401.
    """
    user = user_create(email="profile@example.com")
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/users/me/",
        '{"first_name": "  Ada ", "last_name": "Lovelace"}',
        content_type="application/json",
        secure=True,
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert (user.first_name, user.last_name) == ("Ada", "Lovelace")

    assert (
        Client()
        .post(
            "/api/users/me/",
            "{}",
            content_type="application/json",
            secure=True,
        )
        .status_code
        == 401
    )


@pytest.mark.django_db
def test_profile_update_rejects_names_beyond_the_field_length() -> None:
    """full_clean runs in the service, so an oversized name surfaces as the
    middleware's 400 shape instead of a database error.
    """
    user = user_create(email="long@example.com")
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/users/me/",
        '{"first_name": "' + "x" * 151 + '"}',
        content_type="application/json",
        secure=True,
    )

    assert response.status_code == 400
    assert "message" in response.json()


@pytest.mark.django_db
def test_profile_page_prefills_values_and_the_nav_links_to_it() -> None:
    """The form renders server-side with current values, and the avatar
    dropdown carries the profile link so the page is reachable from any
    screen with the dashboard nav.
    """
    user = user_create(email="render@example.com")
    user.first_name = "Grace"
    user.save(update_fields=["first_name"])

    client = Client()
    assert client.get("/profile/", secure=True).status_code == 302

    client.force_login(user)
    page = client.get("/profile/", secure=True)
    assert page.status_code == 200
    assert b'value="Grace"' in page.content
    assert b'href="/profile/"' in page.content


@pytest.mark.django_db
def test_account_delete_removes_user_rows_and_stored_files(
    memory_storage: Storage,
) -> None:
    """user_delete sweeps the bucket before the row cascade: upload rows
    die with the user via the FK, but their storage objects would survive
    as orphans unless the service deletes them explicitly. The endpoint
    then logs the session out so the browser lands signed out.
    """
    user = user_create(email="doomed@example.com")
    uploads = demo_upload_create_batch(
        user=user,
        files=[
            SimpleUploadedFile("one.txt", b"1", "text/plain"),
            SimpleUploadedFile("two.txt", b"2", "text/plain"),
        ],
    )
    names = [upload.file.name for upload in uploads]

    client = Client()
    client.force_login(user)
    response = client.post("/api/users/me/delete/", secure=True)

    assert response.status_code == 200
    assert not User.objects.filter(email="doomed@example.com").exists()
    assert not DemoUpload.objects.exists()
    for name in names:
        assert name
        assert not memory_storage.exists(name)

    anonymous = Client().post("/api/users/me/delete/", secure=True)
    assert anonymous.status_code == 401


@pytest.mark.django_db
def test_a_users_level_is_their_highest_group() -> None:
    """The users page shows one level per user, so co-membership has to
    collapse deterministically: Developer outranks Admin outranks nothing.
    Superusers hold every permission regardless of groups, so they report
    developer — otherwise an admin could "demote" one in the UI and change
    nothing real.
    """
    user = user_create(email="levels@example.com")
    assert user_level(user) == "basic"

    user.groups.add(Group.objects.get(name="Admin"))
    assert user_level(user) == "admin"

    user.groups.add(Group.objects.get(name="Developer"))
    assert user_level(user) == "developer"

    root = User.objects.create_superuser("root@example.com", "password")
    assert user_level(root) == "developer"


@pytest.mark.django_db
def test_setting_a_level_replaces_group_membership_exactly() -> None:
    """Levels are a ladder, not a pile of flags: setting admin on someone in
    the Developer group must remove Developer, or their level (highest group
    wins) would silently stay developer and the toggle would lie.
    """
    developer = user_create(email="actor@example.com")
    developer.groups.add(Group.objects.get(name="Developer"))
    target = user_create(email="target@example.com")
    target.groups.add(Group.objects.get(name="Developer"))

    user_level_set(actor=developer, user=target, level="admin")
    assert {g.name for g in target.groups.all()} == {"Admin"}
    assert user_level(target) == "admin"

    user_level_set(actor=developer, user=target, level="basic")
    assert target.groups.count() == 0


@pytest.mark.django_db
def test_you_cannot_change_your_own_level() -> None:
    """Self-demotion locks the last developer out of the users page, and
    self-promotion makes the check pointless — so the service rejects the
    actor as the target outright, whatever the direction.
    """
    developer = user_create(email="self@example.com")
    developer.groups.add(Group.objects.get(name="Developer"))

    with pytest.raises(ApplicationError):
        user_level_set(actor=developer, user=developer, level="basic")


@pytest.mark.django_db
def test_levels_can_only_be_granted_up_to_your_own() -> None:
    """An admin manages the ladder below developer: they may toggle others
    between basic and admin, but granting developer would be escalating past
    themselves, and touching an existing developer would be managing upward.
    Both directions fail loudly so the endpoint's 400 carries the reason.
    """
    admin = user_create(email="admin-actor@example.com")
    admin.groups.add(Group.objects.get(name="Admin"))
    basic = user_create(email="basic@example.com")
    developer = user_create(email="dev-target@example.com")
    developer.groups.add(Group.objects.get(name="Developer"))

    user_level_set(actor=admin, user=basic, level="admin")
    assert {g.name for g in basic.groups.all()} == {"Admin"}

    with pytest.raises(ApplicationError):
        user_level_set(actor=admin, user=basic, level="developer")
    with pytest.raises(ApplicationError):
        user_level_set(actor=admin, user=developer, level="basic")


@pytest.mark.django_db
def test_user_search_filters_by_email_and_paginates_newest_first() -> None:
    """The users page is fed entirely by this selector: newest signup first
    so fresh accounts surface, icontains on email so partial queries work,
    and Paginator.get_page so an out-of-range page clamps instead of 404ing
    mid-search. Page size comes from USERS_PER_PAGE, so the test tracks it
    rather than hard-coding 3.
    """
    now = timezone.now()
    emails = [f"person{i}@example.com" for i in range(USERS_PER_PAGE + 2)]
    for i, email in enumerate(emails):
        user_create(email=email)
        User.objects.filter(email=email).update(
            date_joined=now - timedelta(days=i)
        )

    first = user_search()
    assert first["total"] == len(emails)
    assert first["pages"] == 2
    assert [u.email for u in first["users"]] == emails[:USERS_PER_PAGE]

    clamped = user_search(page=99)
    assert clamped["page"] == 2
    assert [u.email for u in clamped["users"]] == emails[USERS_PER_PAGE:]

    match = user_search(query="PERSON0")
    assert [u.email for u in match["users"]] == ["person0@example.com"]


@pytest.mark.django_db
def test_user_search_level_filter_matches_user_level() -> None:
    """The level dropdown must bucket users exactly as user_level reports
    them, or a row could appear under a filter showing a different badge.
    The corner cases are the point: a member of both groups is developer
    (not admin), and a groupless superuser is developer (not basic).
    """
    basic = user_create(email="f-basic@example.com")
    admin = user_create(email="f-admin@example.com")
    admin.groups.add(Group.objects.get(name="Admin"))
    both = user_create(email="f-both@example.com")
    both.groups.add(
        Group.objects.get(name="Admin"), Group.objects.get(name="Developer")
    )
    root = User.objects.create_superuser("f-root@example.com", "password")

    for level, expected in [
        ("basic", {basic.email}),
        ("admin", {admin.email}),
        ("developer", {both.email, root.email}),
    ]:
        result = user_search(level=level)
        assert {u.email for u in result["users"]} == expected, level
        assert all(user_level(u) == level for u in result["users"])
