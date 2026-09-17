# Uninstall the MCP server

Removes the second ASGI service and everything that exists for it:
the `clx/mcp/` tree, the Starlette wrapper in `clx/main.py`,
and django-oauth-toolkit — including the HTTP API's OAuth half, since
the Bearer branch of `authenticate_token` exists for the third-party
clients the consent flow admits, and removing the provider removes
them. API tokens are homegrown and untouched: the `Token` scheme, the
scopes, and every rate-limit bucket stay exactly as they are.
The `clx.main:application` module path stays: compose, the
entrypoint, and the Dockerfile all reference it.

## Remove

1. The whole `clx/mcp/` tree (its tests included).
2. Collapse `clx/main.py` to a plain Django ASGI module:

   ```python
   import os

   from django.core.asgi import get_asgi_application

   os.environ.setdefault("DJANGO_SETTINGS_MODULE", "clx.settings")
   application = get_asgi_application()
   ```

3. `clx/settings.py`: delete `"oauth2_provider"` from
   `INSTALLED_APPS`, the whole `OAUTH2_PROVIDER` dict, and the
   `from clx.app.permissions import API_SCOPES` import that
   exists only to feed it.
4. `clx/app/urls.py`: delete the `oauth2_provider` import,
   `oauth_metadata_patterns`, `oauth_patterns`, and their two
   splices (`*oauth_metadata_patterns` and the `path("o/", ...)`
   include).
5. The `clx/app/template_overrides/oauth2_provider/` directory.
6. `pyproject.toml`: delete the `fastmcp`, `jsonschema`, and
   `django-oauth-toolkit` dependencies, the `types-jsonschema` dev
   dependency, and `"oauth2_provider.*"` from the mypy overrides
   list.
7. `clx/app/tests/test_csp.py`: its `form-action` reasoning
   cites the oauth authorize form — update that docstring to stand
   on the remaining grounds (or adopt `form-action` now that the
   redirect concern is gone; the assertion itself passes either
   way).

## The API's OAuth half

8. `clx/app/selectors/oauth_token.py` (whole file), and in
   `clx/app/api/utils/authentication.py`: the `oauth_token_get`
   import, `_authenticate_oauth_token`, the `Bearer` branch of
   `authenticate_token`, `BEARER_SCHEME`, and the `client` field on
   `Auth` — the `Token` branch is the whole authenticator again.
9. `rate_limit_consume` in `clx/app/api/utils/ratelimit.py` —
   it is the request-free entry point ToolMiddleware charges tool
   calls through, and nothing else calls it.
10. The `"client"` key in `_auth_whoami` in
    `clx/app/api/demos.py` and in `_echo` in
    `clx/app/tests/urls_api_auth.py`.
11. In `clx/app/tests/conftest.py`: the `grant` and
    `bearer_auth` fixtures and the `oauth2_provider` imports. The
    OAuth tests they serve: in `test_api_authentication.py` the
    four `*oauth*`/`*bearer*` tests and
    `test_the_consent_screen_offers_the_api_scope_vocabulary`; in
    `test_api_ratelimit.py`
    `test_the_user_ceiling_is_shared_across_credential_systems` and
    `test_the_scope_budget_is_shared_with_mcp_tool_calls`.

The checks and explorer tolerate the deletion on their own — the MCP
fact extractor and card builder guard their imports — but prune their
dead entries: the `"mcp-tools"` rows of `LAYER_PACKAGES` and
`ALLOWED_IMPORTS` and `check_mcp_direction` (E103) in
`clx/app/checks/imports.py`, `clx.mcp.tools` in
`READ_LAYERS` in `clx/app/checks/calls.py`,
`check_mcp_tools_complete_their_annotations` (E703) in
`clx/app/checks/coverage.py`, their wiring and test cases,
`build_mcp_tools` in `clx/app/selectors/codebase.py`, the
`mcp-tool` row of `CODEBASE_LAYERS` in
`cotton/admin/codebase/explorer.html`, and the MCP tool tests in
`clx/app/tests/test_codebase.py`.

The oauth2 tables disappear with the migration reset that follows
any model-touching guide, or at finalize.

Prune the "## MCP" section of CLAUDE.md, its MCP mentions in the
Permissions section, and the "Two credentials, one header, one scope
vocabulary" bullet there (the `Token` scheme and `API_SCOPES` remain,
but the Bearer half of the story is gone), then run the verify suite.
