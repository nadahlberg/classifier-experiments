# Uninstall API tokens

Removes personal API tokens end to end: the model, its endpoints,
bearer authentication, scopes, and the token-only rate tiers. Session
authentication, `api_auth`, permission checks, and session rate
limiting all stay — no product endpoint outside the demos declares
`TOKEN`, so the product surface is unchanged. **This removes a model:
run the migration reset afterwards.**

## Remove whole files

1. `clx/app/models/api_token.py` (drop the `ApiToken` and
   `TOKEN_PREFIX` re-exports from `clx/app/models/__init__.py`).
2. `clx/app/services/api_token.py` and
   `clx/app/selectors/api_token.py`.
3. `clx/app/api/tokens.py`.
4. `clx/app/tests/test_api_token.py`.

## Shared-file edits

5. `clx/app/urls.py`: delete `tokens_api_patterns`, its
   `path("api/tokens/", ...)` splice, and `tokens` from the api
   import line.
6. `clx/app/api/utils/authentication.py`: delete `TOKEN`,
   `BEARER_SCHEME`, `authenticate_token`, the `TOKEN` entry in
   `AUTHENTICATORS`, and `check_scopes`; shrink `Auth` to
   `user` + `method` (drop `token`, `scopes`, `is_token`) and trim
   `check_perms`'s docstring where it contrasts scopes.
7. `clx/app/api/utils/decorators.py`: drop the `scopes`
   parameter and the `check_scopes` call from `api_auth` (keep
   `perms` and `rate`).
8. `clx/app/api/utils/ratelimit.py`: remove the token-only
   tiers — grep for `is_token`, `api:user`, and `api:scope` and keep
   only the session path.
9. `clx/app/api/utils/__init__.py`: drop the `TOKEN` re-export.
10. `clx/settings.py`: delete `API_TOKEN_MAX_LIFETIME_DAYS`,
    `API_TOKEN_TOUCH_SECONDS`, `API_RATE_LIMIT_PER_USER`,
    `API_RATE_LIMIT_PER_SCOPE_DEFAULT`, and
    `API_RATE_LIMIT_PER_SCOPE`. Keep `API_RATE_LIMIT_PER_SESSION`,
    the window, and the fail-open settings.
11. `clx/app/permissions.py`: delete `API_SCOPES`.

## Tests and demo surface

12. `clx/app/tests/conftest.py`: delete the `mint` and `bearer`
    fixtures and the token service imports.
13. `clx/app/tests/urls_api_auth.py`: drop the `TOKEN` import,
    the `tokens_api_patterns` include, and every throwaway view that
    declares `TOKEN` or `scopes`.
14. `clx/app/tests/test_api_authentication.py` and
    `test_api_ratelimit.py`: delete the token, scope, and per-user /
    per-scope tier tests; keep the session coverage.
15. `clx/app/api/demos.py`: delete the auth demo endpoints that
    exist to show tokens and scopes — `auth_token_only`,
    `auth_session_or_token`, `auth_scoped_read`, `auth_scoped_write`,
    `auth_scoped_both` — and their five `auth/` entries in
    `demos_api_patterns` in `clx/app/urls.py`. Keep `auth_public`,
    `auth_session_only`, `auth_admin_only`, `auth_developer_scoped`,
    and `auth_burst`, dropping `TOKEN` and `scopes=` from their
    `api_auth` calls and `TOKEN` from the module's `api.utils`
    import; shrink `_auth_whoami` to the shrunk `Auth` (the
    `token_name` and `scopes` keys go) and reword the kept
    docstrings that mention tokens or scopes.
16. `clx/app/templates/pages/demos/api.html`: remove the token
    management panel and the endpoint cards that demonstrate token
    auth and scopes; keep the session and permission cards. Trim the
    matching context in the `api` view in
    `clx/app/views/demos.py` (scopes, max lifetime, per-user and
    per-scope limits go; the session limit and permissions stay).

Prune CLAUDE.md wherever it explains scopes (grep for `scope`), then
run the migration reset and the verify suite.
