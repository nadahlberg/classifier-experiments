"""The rate limit tiers, and the relationships between them.

These cover `api/utils/ratelimit.py`: which buckets a request is counted
against, that each is keyed so rotation cannot reset it, and that the
tiers are sized so every one of them can actually bind.
"""

from collections.abc import Callable

import pytest
from django.test import Client
from django.urls import reverse
from pytest_django.fixtures import SettingsWrapper

from clx.app.models import User
from clx.app.services.api_token import MintedToken

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("clx.app.tests.urls_api_auth"),
]


def test_minting_a_new_token_does_not_reset_the_user_ceiling(
    client: Client,
    user: User,
    settings: SettingsWrapper,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """The reason there are two buckets rather than one.

    Every tier that applies to a token is keyed on the user rather than
    on the credential, and this is why: a bucket keyed on the token would
    reset the moment its owner minted a new one, so anyone could consume
    the API without bound just by rotating. Keyed on the user, the budget
    survives rotation and caps them in aggregate however many tokens they
    hold.
    """
    settings.API_RATE_LIMIT_PER_USER = 2
    url = reverse("t-either")
    first_token = mint(user)

    client.get(url, secure=True, headers=token_auth(first_token.plaintext))
    client.get(url, secure=True, headers=token_auth(first_token.plaintext))

    fresh_token = mint(user)
    after_rotation = client.get(
        url, secure=True, headers=token_auth(fresh_token.plaintext)
    )

    assert after_rotation.status_code == 429


def test_one_users_limit_does_not_affect_another(
    client: Client,
    user: User,
    other_user: User,
    settings: SettingsWrapper,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """A shared bucket would let any one caller deny the API to everyone."""
    settings.API_RATE_LIMIT_PER_USER = 1
    url = reverse("t-either")

    client.get(url, secure=True, headers=token_auth(mint(user).plaintext))
    exhausted = client.get(
        url, secure=True, headers=token_auth(mint(user).plaintext)
    )
    neighbour = client.get(
        url, secure=True, headers=token_auth(mint(other_user).plaintext)
    )

    assert exhausted.status_code == 429
    assert neighbour.status_code == 200


def test_a_session_is_not_capped_at_the_token_ceiling(
    client: Client, user: User, settings: SettingsWrapper
) -> None:
    """Sessions and tokens have very different natural volumes.

    The per-user ceiling is sized for machine traffic, which is
    sporadic; a browser is not. The celery demo page alone polls two
    endpoints every two seconds, which is 3600 requests an hour against a
    user ceiling of 2000 -- it would start failing after about half an
    hour.

    So a session gets its own, much looser ceiling, and the two do not
    consume each other. This fails if they are merged back together.
    """
    settings.API_RATE_LIMIT_PER_USER = 1
    settings.API_RATE_LIMIT_PER_SESSION = 50
    client.force_login(user)
    url = reverse("t-session")

    first = client.get(url, secure=True)
    second = client.get(url, secure=True)
    third = client.get(url, secure=True)

    assert [first.status_code, second.status_code, third.status_code] == [
        200,
        200,
        200,
    ]


def test_a_session_still_has_a_ceiling(
    client: Client, user: User, settings: SettingsWrapper
) -> None:
    """Looser is not unlimited; the session tier is still abuse protection."""
    settings.API_RATE_LIMIT_PER_SESSION = 1
    client.force_login(user)
    url = reverse("t-session")

    first = client.get(url, secure=True)
    second = client.get(url, secure=True)

    assert first.status_code == 200
    assert second.status_code == 429


def test_a_scope_budget_is_separate_from_another_scopes(
    client: Client,
    user: User,
    settings: SettingsWrapper,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """The reason scope buckets exist at all.

    Reads are cheap and high volume; writes are expensive and rare. Under a
    single per-user ceiling a polling dashboard eats the whole budget and
    the same user's occasional write starts failing, even though the write
    workload is tiny. Keying a bucket on the scope decouples them, so
    exhausting reads leaves writes untouched.
    """
    settings.API_RATE_LIMIT_PER_USER = 1000
    settings.API_RATE_LIMIT_PER_SCOPE = {"demo:read": 1, "demo:write": 5}
    minted = mint(user)

    first_read = client.get(
        reverse("t-scoped-read"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )
    exhausted_read = client.get(
        reverse("t-scoped-read"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )
    write = client.post(
        reverse("t-scoped-write"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )

    assert first_read.status_code == 200
    assert exhausted_read.status_code == 429
    assert write.status_code == 200


def test_a_scope_budget_is_per_user(
    client: Client,
    user: User,
    other_user: User,
    settings: SettingsWrapper,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """Keyed on the pair, not the scope alone.

    A bucket keyed on the scope by itself would be shared by everyone, so
    one heavy caller could deny that whole scope to every other user.
    """
    settings.API_RATE_LIMIT_PER_USER = 1000
    settings.API_RATE_LIMIT_PER_SCOPE = {"demo:read": 1}
    url = reverse("t-scoped-read")

    client.get(url, secure=True, headers=token_auth(mint(user).plaintext))
    exhausted = client.get(
        url, secure=True, headers=token_auth(mint(user).plaintext)
    )
    neighbour = client.get(
        url, secure=True, headers=token_auth(mint(other_user).plaintext)
    )

    assert exhausted.status_code == 429
    assert neighbour.status_code == 200


def test_rotating_a_token_does_not_reset_a_scope_budget(
    client: Client,
    user: User,
    settings: SettingsWrapper,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """Scope buckets key on the user, so a fresh token inherits the spend."""
    settings.API_RATE_LIMIT_PER_USER = 1000
    settings.API_RATE_LIMIT_PER_SCOPE = {"demo:read": 1}
    url = reverse("t-scoped-read")

    client.get(url, secure=True, headers=token_auth(mint(user).plaintext))
    after_rotation = client.get(
        url, secure=True, headers=token_auth(mint(user).plaintext)
    )

    assert after_rotation.status_code == 429


def test_an_endpoint_counts_against_every_scope_it_requires(
    client: Client,
    user: User,
    settings: SettingsWrapper,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """A call that uses two scopes spends from both budgets.

    Charging only one of them would let an endpoint requiring several
    scopes be used to drain past the tighter of its budgets, which is the
    one that expresses the real cost.
    """
    settings.API_RATE_LIMIT_PER_USER = 1000
    settings.API_RATE_LIMIT_PER_SCOPE = {"demo:read": 50, "demo:write": 1}
    minted = mint(user)

    allowed = client.post(
        reverse("t-scoped-both"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )
    blocked_by_the_tighter_scope = client.post(
        reverse("t-scoped-both"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )
    write_alone = client.post(
        reverse("t-scoped-write"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )

    assert allowed.status_code == 200
    assert blocked_by_the_tighter_scope.status_code == 429
    assert write_alone.status_code == 429


def test_an_unscoped_endpoint_uses_the_default_budget(
    client: Client,
    user: User,
    settings: SettingsWrapper,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """Every token request lands in some bucket, declared scope or not.

    Without a fallback, an endpoint that declares no scopes would skip the
    scope tier entirely and be limited only by the much looser user and
    token ceilings -- so the easiest way to escape a scope budget would be
    to forget to declare one.
    """
    settings.API_RATE_LIMIT_PER_USER = 1000
    settings.API_RATE_LIMIT_PER_SCOPE_DEFAULT = 1
    settings.API_RATE_LIMIT_PER_SCOPE = {}
    minted = mint(user)
    url = reverse("t-either")

    first = client.get(url, secure=True, headers=token_auth(minted.plaintext))
    second = client.get(url, secure=True, headers=token_auth(minted.plaintext))

    assert first.status_code == 200
    assert second.status_code == 429


def test_the_user_ceiling_is_shared_across_credential_systems(
    client: Client,
    user: User,
    settings: SettingsWrapper,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
    grant: Callable[..., str],
    bearer_auth: Callable[[str], dict[str, str]],
) -> None:
    """One aggregate ceiling, however the user's machines arrive.

    Token buckets key on the user, not the credential, so a consented OAuth
    client and a personal token spend from one budget. This is also what
    pins the branch in _rate_limits to auth.is_token rather than auth.token:
    an OAuth Auth carries no ApiToken row, and keying the branch on the row
    would silently hand every consented client the much looser session
    ceiling instead.
    """
    settings.API_RATE_LIMIT_PER_USER = 2
    url = reverse("t-either")

    client.get(url, secure=True, headers=bearer_auth(grant(user)))
    client.get(url, secure=True, headers=token_auth(mint(user).plaintext))
    third = client.get(url, secure=True, headers=bearer_auth(grant(user)))

    assert third.status_code == 429


def test_the_scope_budget_is_shared_with_mcp_tool_calls(
    client: Client,
    user: User,
    settings: SettingsWrapper,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """rate_limit_consume spends from the same buckets rate_limit_apply reads.

    rate_limit_consume is the request-free entry point ToolMiddleware
    charges MCP tool calls through. If it ever grew its own group names or
    key shapes, MCP traffic would stop counting against the user's HTTP
    budgets and the aggregate ceiling would quietly stop being aggregate --
    so this drains a scope through the MCP entry point and asserts the HTTP
    side finds the bucket empty.
    """
    from clx.app.api.utils.ratelimit import rate_limit_consume

    settings.API_RATE_LIMIT_PER_USER = 1000
    settings.API_RATE_LIMIT_PER_SCOPE = {"demo:read": 1}

    rate_limit_consume(user_id=user.pk, scopes=("demo:read",))
    over_http = client.get(
        reverse("t-scoped-read"),
        secure=True,
        headers=token_auth(mint(user).plaintext),
    )

    assert over_http.status_code == 429


def test_a_session_is_not_scope_limited(
    client: Client, user: User, settings: SettingsWrapper
) -> None:
    """Sessions carry no scopes, so the scope tier does not apply to them.

    A session is a person clicking, already bounded by the user ceiling.
    Charging it to a scope budget would let browser use exhaust the budget
    a token workload depends on, and there is no scope on the credential to
    charge it to in the first place.
    """
    settings.API_RATE_LIMIT_PER_USER = 1000
    settings.API_RATE_LIMIT_PER_SCOPE = {"demo:read": 1}
    client.force_login(user)
    url = reverse("t-scoped-read")

    first = client.get(url, secure=True)
    second = client.get(url, secure=True)

    assert first.status_code == 200
    assert second.status_code == 200


def test_every_scope_budget_is_reachable() -> None:
    """A scope budget above the user ceiling can never bind.

    The user tier is a backstop that catches abuse spread across scopes;
    the scope tier is what actually shapes a workload. Put a scope budget
    above the ceiling and the ceiling binds first, so that budget is
    decorative -- worse than absent, because the demo page prints it beside
    the scope as if it applied.

    The ceiling is a deliberate number rather than one derived from the
    budgets, so this asserts the relationship rather than enforcing it:
    raising a scope budget past the ceiling should make someone choose a
    new ceiling, not silently move it.

    It reads the settings module rather than django.conf.settings because
    other tests in this file override these values to isolate one tier.
    """
    from clx import settings as configured

    budgets = [
        *configured.API_RATE_LIMIT_PER_SCOPE.values(),
        configured.API_RATE_LIMIT_PER_SCOPE_DEFAULT,
    ]

    assert max(budgets) <= configured.API_RATE_LIMIT_PER_USER


def test_fail_open_setting_reaches_the_package() -> None:
    """Our setting is only documentation unless the package reads it.

    django-ratelimit looks at RATELIMIT_FAIL_OPEN and has never heard of
    API_RATE_LIMIT_FAIL_OPEN, so the two have to stay wired together. If
    they came apart, editing the setting in settings.py would silently do
    nothing, and with the package falling back to its own default -- fail
    closed -- a cache outage would start rejecting every authenticated
    request instead of letting them through.

    It reads the settings module rather than django.conf.settings for the
    same reason as the test above: other tests override these values.
    """
    from clx import settings as configured

    assert (
        configured.RATELIMIT_FAIL_OPEN is configured.API_RATE_LIMIT_FAIL_OPEN
    )


def test_the_silenced_check_is_only_hiding_an_untested_backend() -> None:
    """django_ratelimit.W001 is silenced, so it must stay harmless.

    The package keeps an allowlist of three cache backends it has tested,
    and Django's own RedisCache is not on it -- the list predates that
    backend being common. It keeps a separate list of backends that are
    genuinely broken for rate limiting, because they are fake, per-process,
    or cannot increment atomically, and ours is not on that one.

    Silencing the warning is therefore fine today and would stop being fine
    the moment the cache moved to locmem, the database or the filesystem,
    where the counter would either be wrong or invisible to other workers.
    This fails if that happens, since the silenced warning would then be
    covering a real defect rather than a stale allowlist.

    It reads the settings module rather than django.conf.settings because
    the suite's own fixture swaps in locmem -- which is on the broken list,
    and correctly so: a per-process counter is right for a single-process
    test and wrong for the deployed app.
    """
    from django_ratelimit.checks import KNOWN_BROKEN_CACHE_BACKENDS

    from clx import settings as configured

    backend = configured.CACHES["default"]["BACKEND"]

    assert "django_ratelimit.W001" in configured.SILENCED_SYSTEM_CHECKS
    assert backend not in KNOWN_BROKEN_CACHE_BACKENDS
