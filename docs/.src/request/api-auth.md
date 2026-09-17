# API authentication

Every endpoint under `api/` declares who may call it with one decorator:
[`api_auth`](sym:20b2bdd28b9f+,d97a7c6216e1). The declaration is the whole
story — methods, permissions, scopes and an optional burst rate in one
place — and rule E701 makes the declaration mandatory, so "public" is
something an endpoint says (`@api_auth(PUBLIC)`) rather than something it
forgets.

## The three method constants

[`SESSION`](sym:0aaeb9f93631), [`TOKEN`](sym:6a9306c4cb7c) and
[`PUBLIC`](sym:3d55b6fea4d0) name the acceptable ways in. Methods compose
disjunctively — `@api_auth(SESSION, TOKEN)` accepts either — except
`PUBLIC`, which skips authentication entirely and raises `ValueError` at
decoration time if combined with anything, including `perms`, `scopes` or
`rate`: an anonymous request has no user to hold anything against, so the
combination is always a bug.

## Resolving the caller

[`resolve_auth`](sym:5bb10c774ffb+) tries [each allowed method's
authenticator](sym:12dd95b5d597,2b8bd7284fd6,81611433ef94,17c00bca29c6,e70d5ebe97b1)
in declaration order and returns the first
[`Auth`](sym:697180e8f259+) — a frozen dataclass carrying the user, the
method, the token row or OAuth client name, and the credential's scopes.

[`authenticate_session`](sym:08d567b060ed+) accepts a logged-in session
and then [re-enforces CSRF by hand](sym:d39d0c17ca41+,140c101fea4e),
because `api_auth` exempts the view from Django's CSRF middleware (a token
request carries no cookie and must not be asked for a CSRF token) — so the
session path re-runs the exact middleware check the exemption skipped.

[`authenticate_token`](sym:3f45b1fde601+) reads the `Authorization` header
and dispatches on the scheme, compared case-insensitively:
[`Token`](sym:d59da594ecfe) means a personal API token,
[`Bearer`](sym:c071ec5522b3) means an OAuth access token. The scheme names
the credential system, so presenting one as the other gets a targeted
error — [`_authenticate_oauth_token`](sym:5ba6573b15a3+) recognises an API
token's shape and answers "send it as `Authorization: Token ...`" instead
of a generic rejection. [`_authenticate_api_token`](sym:72541e30c4e9+)
splits the presented value into id and secret, compares hashes in constant
time (`secrets.compare_digest`, so a wrong secret costs the same as a
right one), rejects revoked, expired and deactivated-owner tokens with
distinct messages, and touches `last_used_at`. Both paths yield the same
`Auth` shape, which is why every `TOKEN` endpoint accepts either
credential without knowing which arrived.

## Permissions and scopes

Two checks with deliberately different reach:
[`check_perms`](sym:682e0e19292c+) binds the *user* — a permission is a
fact about who is calling, so it applies to sessions and tokens alike —
while [`check_scopes`](sym:a20be3e9e172+) binds the *credential*, holding
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

[`frame_self`](sym:a9d218b90b48+) is the one other response-shaping
decorator in the package root: it relaxes the global
`frame-ancestors 'none'` CSP to `'self'` for a response our own pages
frame, such as the upload preview.

## The test URLconf

The machinery's tests own their URLconf:
[`urls_api_auth.py`](sym:be291dd7dc3f,bef38cac9851) declares [one
throwaway endpoint per
rule](sym:9d65dfdc1139,ddc4d6dbf572,671210a7a71e,72ac4510ed15,00c4ae34ad90,9be056a71acd,687c369d7741,d8b37b81e183,9a30f9627321,defb79b5a65b,60be77782f51,e74d870fa9d1,69e248684021,dfb2b24e51f9,9a01c9dbf79c,318e831baf44,4fdda8510da4)
— open, public, session-only, token-only, either, each scope shape, each
permission shape, a burst-rated one, and an async one, each
[echoing the resolved `Auth`
back](sym:968c29a6e726,c1d005549027,3a0a6a555d20,c0a96f3c4430,4a75f2be567e,2e28e4b2e502,ee361c1dacbc,016339c2b150,3bf93218e2ae,becd44efc8e6,3fe1174f3f2d,78ace64727c9,834aaccd7ea2,9e5b16e3d81a,c178956985e3,711f73378364,8eab76bc9c31,818627efbff5,45072c59507e)
as JSON. The tests point at it with `pytest.mark.urls`, so what is covered
is the machinery itself rather than whichever demo endpoint happened to use
it — the demo surface is designed to be deleted, and these tests must
survive that. The token API is included as-is because it is real product
surface.

## What the tests pin

[`test_api_authentication.py`](sym:6ad6d2f2bb4a) walks the whole contract.
The API-token lifecycle: [a valid token authenticates and the echo shows
its name and scopes](sym:9270c06336ea), while [garbage](sym:676bff6c1a85),
[revoked](sym:15d5d0a66c8c), [expired](sym:17dfc98cf5e8) and
[deactivated-owner](sym:b0bf30b314dd) tokens all get 401s, and [the scheme
matches case-insensitively](sym:c5943fb100a8). The OAuth half:
[a bearer token authenticates and reports its client](sym:6c771a95298d),
[expiry is enforced](sym:033febeae6ad), [scopes are
enforced](sym:170fd7ccc320), [an application-less token still
works](sym:62218f885e38), [an API token sent as Bearer gets the
targeted redirect-to-scheme error](sym:56b57536a6e3), and [the consent
screen offers exactly the `API_SCOPES` vocabulary](sym:73b46f084307+).

Method composition: [the public endpoint needs no
credentials](sym:00978e908610) and [answers anonymously](sym:d279bfacd5ef),
[session-only rejects a token](sym:ea6bb7ecea98), [token-only rejects a
session](sym:44dba14dcc3a), [either accepts both](sym:36ad10c5b576), and
[`PUBLIC` composed with anything raises at import
time](sym:c6e5fbd1ea80). CSRF splits by path: [session writes still
require the token](sym:d3b05ef3e000), [token writes do not](sym:3860967eef61).
Scopes and permissions interact the documented way: [a token is held to
its scopes](sym:ce9072df3f54) but [a session is not](sym:f97baafb5929);
[a permission gates tokens](sym:bf7e4e7bfcbd) [and sessions
alike](sym:61a1903f175c); [an endpoint can require both a permission and a
scope, and a token missing either is refused](sym:cba44cb9d3df); [a
permission the caller's group does not carry is refused](sym:9ec2bedbbb2f).
Finally the wrapper itself: [async views authenticate
identically](sym:c3b7c6db383f) and [the stamped config matches the
declaration](sym:de61e1833e7b+).
