"""The authenticator chain: who is calling, and may they.

These cover `api/utils/authentication.py` and the `perms=` and `scopes=`
arguments to `api_auth`. They run against `tests/urls_api_auth.py` so that
what is under test is the machinery rather than any endpoint that happens
to use it.
"""

from collections.abc import Callable
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from clx.app.models import User
from clx.app.services.api_token import MintedToken

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("clx.app.tests.urls_api_auth"),
]


def test_a_valid_token_authenticates(
    client: Client,
    user: User,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """The happy path for a headless caller."""
    minted = mint(user)

    response = client.get(
        reverse("t-token"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )

    assert response.status_code == 200
    assert response.json()["auth_method"] == "token"
    assert response.json()["user"] == user.email


@pytest.mark.parametrize(
    "mangle",
    [
        lambda p: "pat_nope_nope",
        lambda p: p + "x",
        lambda p: "garbage",
    ],
)
def test_a_bad_token_is_rejected(
    client: Client,
    user: User,
    mangle: Callable[[str], str],
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """A wrong secret must fail even though the lookup id is real.

    The id half of the token is a public index, so presenting a valid id
    with a wrong secret is the attack this guards: only the constant-time
    hash comparison separates them.
    """
    minted = mint(user)

    response = client.get(
        reverse("t-token"),
        secure=True,
        headers=token_auth(mangle(minted.plaintext)),
    )

    assert response.status_code == 401


def test_a_revoked_token_stops_working(
    client: Client,
    user: User,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """Revocation is the only lever a user has once a token leaks."""
    minted = mint(user)
    minted.token.revoked_at = timezone.now()
    minted.token.save()

    response = client.get(
        reverse("t-token"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )

    assert response.status_code == 401


def test_an_expired_token_stops_working(
    client: Client,
    user: User,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """Every token expires; an expired one must not authenticate."""
    minted = mint(user)
    minted.token.expires_at = timezone.now() - timedelta(seconds=1)
    minted.token.save()

    response = client.get(
        reverse("t-token"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )

    assert response.status_code == 401


def test_the_authorization_scheme_is_case_insensitive(
    client: Client,
    user: User,
    mint: Callable[..., MintedToken],
    grant: Callable[..., str],
) -> None:
    """RFC 7235 makes auth schemes case-insensitive, and clients rely on it.

    Prefix-matching the literal `Token ` / `Bearer ` would silently reject
    `token`/`BEARER` from clients and proxies that normalise casing --
    and since the scheme is what routes a credential to its system, the
    failure would read as a bad token rather than a spelling mismatch.
    """
    with_pat = client.get(
        reverse("t-token"),
        secure=True,
        headers={"Authorization": f"tOkEn {mint(user).plaintext}"},
    )
    with_oauth = client.get(
        reverse("t-token"),
        secure=True,
        headers={"Authorization": f"BEARER {grant(user)}"},
    )

    assert with_pat.status_code == 200
    assert with_pat.json()["token_name"] == "test token"
    assert with_oauth.status_code == 200
    assert with_oauth.json()["client"] == "Test Client"


def test_a_deactivated_users_token_stops_working(
    client: Client,
    user: User,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """Deactivation severs machine access the way it severs login.

    Django's ModelBackend refuses inactive users, so sessions die the
    moment an account is deactivated -- but a token authenticates outside
    that backend, and without its own check it would keep working until it
    happened to expire. The OAuth path and the MCP resolver both refuse
    inactive users; this pins the API-token path to match.
    """
    minted = mint(user)
    user.is_active = False
    user.save()

    response = client.get(
        reverse("t-token"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )

    assert response.status_code == 401


def test_an_oauth_token_authenticates_over_bearer(
    client: Client,
    user: User,
    grant: Callable[..., str],
    bearer_auth: Callable[[str], dict[str, str]],
) -> None:
    """OAuth access tokens are first-class credentials on the HTTP API.

    A third-party client the user consented to reaches the same endpoints
    a personal token does. The scheme names the system -- `Token` for API
    tokens, `Bearer` for OAuth -- so the two share one header without
    colliding, and both resolve to the same Auth so everything downstream
    (perms, scopes, rate limits) treats them alike.
    """
    response = client.get(
        reverse("t-token"),
        secure=True,
        headers=bearer_auth(grant(user)),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["auth_method"] == "token"
    assert body["token_name"] is None
    assert body["client"] == "Test Client"
    assert body["scopes"] == ["demo:read", "demo:write"]


def test_an_expired_oauth_token_is_rejected(
    client: Client,
    user: User,
    grant: Callable[..., str],
    bearer_auth: Callable[[str], dict[str, str]],
) -> None:
    """The row existing is not enough; DOT's own is_valid() must agree."""
    token = grant(user, expires_in=-1)

    response = client.get(
        reverse("t-token"), secure=True, headers=bearer_auth(token)
    )

    assert response.status_code == 401


def test_an_oauth_token_is_held_to_its_scopes(
    client: Client,
    user: User,
    grant: Callable[..., str],
    bearer_auth: Callable[[str], dict[str, str]],
) -> None:
    """The grant's scopes bind exactly like a minted token's.

    One scope vocabulary is the whole point: the consent screen, the MCP
    resource metadata, and this check all speak API_SCOPES, so a token
    granted demo:read alone must read and not write.
    """
    headers = bearer_auth(grant(user, scope="demo:read"))

    allowed = client.get(
        reverse("t-scoped-read"), secure=True, headers=headers
    )
    denied = client.post(
        reverse("t-scoped-write"), secure=True, headers=headers
    )

    assert allowed.status_code == 200
    assert denied.status_code == 403


def test_an_oauth_token_without_an_application_still_authenticates(
    client: Client,
    user: User,
    bearer_auth: Callable[[str], dict[str, str]],
) -> None:
    """DOT allows application to be null, so the auth path must tolerate it.

    The consent flow always attaches an application, but a token created by
    hand in the admin need not carry one -- and `access.application.name`
    on that row is an AttributeError, which surfaces as a 500 instead of
    an auth decision. The client field is simply absent for such a token.
    """
    from oauth2_provider.models import get_access_token_model

    get_access_token_model().objects.create(
        user=user,
        token="appless-token",
        expires=timezone.now() + timedelta(hours=1),
        scope="demo:read",
    )

    response = client.get(
        reverse("t-token"),
        secure=True,
        headers=bearer_auth("appless-token"),
    )

    assert response.status_code == 200
    assert response.json()["client"] is None


def test_an_api_token_sent_as_bearer_is_pointed_at_the_scheme(
    client: Client,
    user: User,
    mint: Callable[..., MintedToken],
) -> None:
    """The one wrong-system mistake that is detectable gets a targeted error.

    A pat_-shaped credential under Bearer is unambiguous: it is one of
    ours, and it belongs under the Token scheme. The generic 'Invalid
    bearer token' would send its holder off to debug a perfectly good
    token; the error names the actual fix instead.
    """
    minted = mint(user)

    response = client.get(
        reverse("t-token"),
        secure=True,
        headers={"Authorization": f"Bearer {minted.plaintext}"},
    )

    assert response.status_code == 401
    assert "Authorization: Token" in response.json()["message"]


def test_the_consent_screen_offers_the_api_scope_vocabulary() -> None:
    """OAUTH2_PROVIDER registers API_SCOPES, so there is only one vocabulary.

    A scope the consent screen offers but the API never checks is noise; a
    scope the API checks but no client can be granted is a lockout. Building
    the OAuth SCOPES dict from API_SCOPES keeps the two from drifting, and
    the defaults must be a subset or an unscoped client gets grants nothing
    recognises.
    """
    from typing import cast

    from django.conf import settings

    from clx.app.permissions import API_SCOPES

    defaults = cast("list[str]", settings.OAUTH2_PROVIDER["DEFAULT_SCOPES"])

    assert settings.OAUTH2_PROVIDER["SCOPES"] == API_SCOPES
    assert set(defaults) <= set(API_SCOPES)


def test_the_public_endpoint_needs_no_credentials(client: Client) -> None:
    """Health and friends stay open; not every endpoint should be gated."""
    response = client.get(reverse("t-open"), secure=True)

    assert response.status_code == 200


def test_session_only_endpoint_rejects_a_token(
    client: Client,
    user: User,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """The methods must come apart, not collapse into one blanket check.

    A valid token is still the wrong credential here, which is the whole
    point of declaring methods per endpoint.
    """
    minted = mint(user)

    response = client.get(
        reverse("t-session"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )

    assert response.status_code == 401


def test_token_only_endpoint_rejects_a_session(
    client: Client, user: User
) -> None:
    """The mirror image: a browser session is wrong for a machine endpoint."""
    client.force_login(user)

    response = client.get(reverse("t-token"), secure=True)

    assert response.status_code == 401


def test_either_endpoint_accepts_both(
    client: Client,
    user: User,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """Disjunctive composition: the chain takes the first method that wins."""
    minted = mint(user)
    with_token = client.get(
        reverse("t-either"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )

    client.force_login(user)
    with_session = client.get(reverse("t-either"), secure=True)

    assert with_token.status_code == 200
    assert with_token.json()["auth_method"] == "token"
    assert with_session.status_code == 200
    assert with_session.json()["auth_method"] == "session"


def test_session_writes_still_require_csrf(user: User) -> None:
    """The trap in mixing the two methods.

    Endpoints are exempted from Django's CSRF middleware so that a token
    request is never asked for a CSRF token it cannot have. That exemption
    would silently remove CSRF protection from cookie-authenticated writes
    if the session authenticator did not re-enforce it on its own path.
    """
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(user)

    response = csrf_client.post(reverse("t-scoped-write"), secure=True)

    assert response.status_code == 403


def test_token_writes_do_not_require_csrf(
    user: User,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """The other half: a token carries no cookie, so there is no CSRF risk.

    Demanding a CSRF token here would break every non-browser client, which
    is why the exemption exists in the first place.
    """
    csrf_client = Client(enforce_csrf_checks=True)
    minted = mint(user)

    response = csrf_client.post(
        reverse("t-scoped-write"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )

    assert response.status_code == 200


def test_a_token_is_held_to_its_scopes(
    client: Client,
    user: User,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """A token should be able to do less than its owner, never more."""
    minted = mint(user, scopes=["demo:read"])

    allowed = client.get(
        reverse("t-scoped-read"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )
    denied = client.post(
        reverse("t-scoped-write"),
        secure=True,
        headers=token_auth(minted.plaintext),
    )

    assert allowed.status_code == 200
    assert denied.status_code == 403


def test_a_session_is_not_held_to_token_scopes(
    client: Client, user: User
) -> None:
    """Scopes narrow a credential, and a session is the user themselves.

    Applying token scopes to a session would lock a logged-in user out of
    their own pages, since a session carries no scopes at all.
    """
    client.force_login(user)

    response = client.get(reverse("t-scoped-read"), secure=True)

    assert response.status_code == 200


def test_a_permission_gates_the_endpoint(
    client: Client,
    user: User,
    admin_user: User,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """The permission tier, which binds the user rather than the credential.

    A caller without the permission is refused and one with it is let
    through, on the same endpoint with the same kind of credential.
    """
    denied = client.get(
        reverse("t-admin"),
        secure=True,
        headers=token_auth(mint(user).plaintext),
    )
    allowed = client.get(
        reverse("t-admin"),
        secure=True,
        headers=token_auth(mint(admin_user).plaintext),
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200


def test_a_permission_binds_a_session_too(client: Client, user: User) -> None:
    """Unlike scopes, a permission is a fact about the user.

    Scopes narrow a token and leave a session alone, because a session
    carries the user's full rights. A permission is not about the
    credential at all, so it must apply whichever way the caller arrived --
    otherwise logging in through a browser would be a way around it.
    """
    client.force_login(user)

    response = client.get(reverse("t-admin"), secure=True)

    assert response.status_code == 403


def test_a_token_needs_the_permission_and_the_scope(
    client: Client,
    admin_user: User,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """They compose, and the narrower of the two is what binds.

    A token's rights are its owner's permissions intersected with its own
    scopes, so holding the permission is not enough if the token was minted
    without the scope.
    """
    without_scope = mint(admin_user, scopes=[])
    with_scope = mint(admin_user, scopes=["demo:read"])

    denied = client.get(
        reverse("t-admin-and-scope"),
        secure=True,
        headers=token_auth(without_scope.plaintext),
    )
    allowed = client.get(
        reverse("t-admin-and-scope"),
        secure=True,
        headers=token_auth(with_scope.plaintext),
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200


def test_a_permission_the_group_does_not_carry_is_refused(
    client: Client,
    admin_user: User,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """Admin is not Developer; the groups are not nested.

    This fails if the two permissions are ever collapsed into one, which is
    the mistake the two-group table in permissions.py exists to prevent.
    """
    response = client.get(
        reverse("t-developer"),
        secure=True,
        headers=token_auth(mint(admin_user).plaintext),
    )

    assert response.status_code == 403


def test_api_auth_wraps_async_views(
    client: Client,
    user: User,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """The decorator authenticates coroutine views with the same semantics.

    The SSE relay is an async view behind the same api_auth as every sync
    endpoint. This fails if the decorator ever assumes a sync view again —
    the coroutine would be called without auth resolving, or not awaited
    at all.
    """
    anonymous = client.get(reverse("t-async"), secure=True)

    client.force_login(user)
    session = client.get(reverse("t-async"), secure=True)

    client.logout()
    token = client.get(
        reverse("t-async"),
        secure=True,
        headers=token_auth(mint(user).plaintext),
    )

    assert anonymous.status_code == 401
    assert session.json()["auth_method"] == "session"
    assert token.json()["auth_method"] == "token"


def test_api_auth_exposes_its_config() -> None:
    """api_auth stashes its resolved configuration on the wrapper, beside
    the existing api_view marker, and the pattern checks read an
    endpoint's auth contract off that attribute instead of parsing the
    decorator's source. functools.wraps copies __dict__ outward, so the
    stash must survive csrf_exempt and any require_* decorator wrapped
    around it. This fails if the stash is dropped, renamed, or stops
    reflecting the defaults.
    """
    from django.http import HttpRequest, HttpResponse
    from django.views.decorators.http import require_POST

    from clx.app.api.utils import SESSION, TOKEN, api_auth

    @require_POST
    @api_auth(
        SESSION,
        TOKEN,
        perms=["app.manage_admin"],
        scopes=["demo:read"],
        rate=(5, 60),
    )
    def endpoint(request: HttpRequest) -> HttpResponse:
        return HttpResponse()

    assert endpoint.api_auth == {  # type: ignore[attr-defined]
        "methods": (SESSION, TOKEN),
        "perms": ("app.manage_admin",),
        "scopes": ("demo:read",),
        "rate": (5, 60),
    }

    @api_auth()
    def bare(request: HttpRequest) -> HttpResponse:
        return HttpResponse()

    assert bare.api_auth == {  # type: ignore[attr-defined]
        "methods": (SESSION,),
        "perms": (),
        "scopes": (),
        "rate": None,
    }


def test_a_public_endpoint_answers_anonymously(client: Client) -> None:
    """@api_auth(PUBLIC) is how an endpoint is open on purpose.

    An endpoint with no api_auth at all is indistinguishable from one
    someone forgot to guard, which is why the pattern checks (app.E701)
    reject it. PUBLIC makes openness a declaration: the wrapper skips
    authentication entirely and the stash records the decision, so the
    checks and the explorer both see "public by choice".
    """
    response = client.get(reverse("t-public"), secure=True)

    assert response.status_code == 200
    assert response.json() == {"auth_method": None}


def test_public_composes_with_nothing() -> None:
    """PUBLIC beside another method, perms, scopes, or a rate raises.

    Each of those declarations only means something after a caller is
    resolved, and PUBLIC's whole contract is that no caller is. Failing
    at decoration time turns a contradictory declaration into an import
    error instead of an endpoint that silently ignores half its config.
    """
    from clx.app.api.utils import PUBLIC, SESSION, api_auth

    for kwargs in (
        {"perms": ["app.manage_admin"]},
        {"scopes": ["demo:read"]},
        {"rate": (5, 60)},
    ):
        with pytest.raises(ValueError, match="PUBLIC"):
            api_auth(PUBLIC, **kwargs)
    with pytest.raises(ValueError, match="PUBLIC"):
        api_auth(PUBLIC, SESSION)
