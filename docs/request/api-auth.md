# API authentication

Every endpoint under `api/` declares who may call it with one decorator:
[`api_auth`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/decorators.py#L30-L110). The declaration is the whole
story — methods, permissions, scopes and an optional burst rate in one
place — and rule E701 makes the declaration mandatory, so "public" is
something an endpoint says (`@api_auth(PUBLIC)`) rather than something it
forgets.

## The three method constants

[`SESSION`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L17), [`TOKEN`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L18) and
[`PUBLIC`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L19) name the acceptable ways in. Methods compose
disjunctively — `@api_auth(SESSION, TOKEN)` accepts either — except
`PUBLIC`, which skips authentication entirely and raises `ValueError` at
decoration time if combined with anything, including `perms`, `scopes` or
`rate`: an anonymous request has no user to hold anything against, so the
combination is always a bug.

## Resolving the caller

[`resolve_auth`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L124-L130) tries [each allowed method's
authenticator](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L118-L121)
in declaration order and returns the first
[`Auth`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L26-L36) — a frozen dataclass carrying the user, the
method, the token row or OAuth client name, and the credential's scopes.

[`authenticate_session`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L51-L57) accepts a logged-in session
and then [re-enforces CSRF by hand](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L43-L48),
because `api_auth` exempts the view from Django's CSRF middleware (a token
request carries no cookie and must not be asked for a CSRF token) — so the
session path re-runs the exact middleware check the exemption skipped.

[`authenticate_token`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L107-L115) reads the `Authorization` header
and dispatches on the scheme, compared case-insensitively:
[`Token`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L21) means a personal API token,
[`Bearer`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L22) means an OAuth access token. The scheme names
the credential system, so presenting one as the other gets a targeted
error — [`_authenticate_oauth_token`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L87-L104) recognises an API
token's shape and answers "send it as `Authorization: Token ...`" instead
of a generic rejection. [`_authenticate_api_token`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L60-L84)
splits the presented value into id and secret, compares hashes in constant
time (`secrets.compare_digest`, so a wrong secret costs the same as a
right one), rejects revoked, expired and deactivated-owner tokens with
distinct messages, and touches `last_used_at`. Both paths yield the same
`Auth` shape, which is why every `TOKEN` endpoint accepts either
credential without knowing which arrived.

## Permissions and scopes

Two checks with deliberately different reach:
[`check_perms`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L144-L154) binds the *user* — a permission is a
fact about who is calling, so it applies to sessions and tokens alike —
while [`check_scopes`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/authentication.py#L133-L141) binds the *credential*, holding
only tokens to their scope list; a session carries the user's full rights.
A token's effective rights are therefore its owner's permissions
intersected with its own scopes. Both raise `PermissionDeniedError`
naming exactly what is missing.

## What the decorator assembles

For a non-public endpoint, `api_auth` runs resolve → perms → scopes →
[rate limits](ratelimit.md), stashes the `Auth` on `request.auth` and the
user on `request.user`, calls the view, and stamps
`X-RateLimit-Limit`/`X-RateLimit-Remaining` on the response. It wraps sync
and async views alike (the async path pushes the whole authorization
through `sync_to_async`), and stamps two attributes on the wrapper:
`api_view` (which opts the view into
[JSON error rendering](errors.md)) and `api_auth` (the config dict the
E701 check and the tests read).

[`frame_self`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/decorators.py#L24-L27) is the one other response-shaping
decorator in the package root: it relaxes the global
`frame-ancestors 'none'` CSP to `'self'` for a response our own pages
frame, such as the upload preview.

## The test URLconf

The machinery's tests own their URLconf:
[`urls_api_auth.py`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/urls_api_auth.py#L77-L92) declares [one
throwaway endpoint per
rule](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/urls_api_auth.py#L25-L35)
— open, public, session-only, token-only, either, each scope shape, each
permission shape, a burst-rated one, and an async one, each
[echoing the resolved `Auth`
back](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/urls_api_auth.py#L73)
as JSON. The tests point at it with `pytest.mark.urls`, so what is covered
is the machinery itself rather than whichever demo endpoint happened to use
it — the demo surface is designed to be deleted, and these tests must
survive that. The token API is included as-is because it is real product
surface.

## What the tests pin

[`test_api_authentication.py`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L20-L23) walks the whole contract.
The API-token lifecycle: [a valid token authenticates and the echo shows
its name and scopes](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L26-L43), while [garbage](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L54-L75),
[revoked](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L78-L95), [expired](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L98-L115) and
[deactivated-owner](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L148-L172) tokens all get 401s, and [the scheme
matches case-insensitively](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L118-L145). The OAuth half:
[a bearer token authenticates and reports its client](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L175-L200),
[expiry is enforced](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L203-L216), [scopes are
enforced](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L219-L241), [an application-less token still
works](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L244-L272), [an API token sent as Bearer gets the
targeted redirect-to-scheme error](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L275-L296), and [the consent
screen offers exactly the `API_SCOPES` vocabulary](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L299-L317).

Method composition: [the public endpoint needs no
credentials](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L320-L324) and [answers anonymously](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L626-L638),
[session-only rejects a token](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L327-L346), [token-only rejects a
session](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L349-L357), [either accepts both](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L360-L380), and
[`PUBLIC` composed with anything raises at import
time](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L641-L659). CSRF splits by path: [session writes still
require the token](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L383-L396), [token writes do not](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L399-L418).
Scopes and permissions interact the documented way: [a token is held to
its scopes](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L421-L442) but [a session is not](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L445-L457);
[a permission gates tokens](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L460-L484) [and sessions
alike](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L487-L499); [an endpoint can require both a permission and a
scope, and a token missing either is refused](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L502-L529); [a
permission the caller's group does not carry is refused](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L532-L549).
Finally the wrapper itself: [async views authenticate
identically](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L552-L579) and [the stamped config matches the
declaration](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_authentication.py#L582-L623).
