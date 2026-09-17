# Uninstall the admin surface

Removes the hand-rolled admin pages (settings, users) and their API.
Two things stay on purpose: `clx/app/permissions.py` — groups,
the dev-user seeding, and any MCP tool still bind to it — and
`site_config_update`, the documented cache-busting exemplar, which
keeps working headless. Django's own contrib admin was never
installed.

## Remove whole files

1. `clx/app/views/admin.py` and `clx/app/api/admin.py`.
2. `clx/app/templates/pages/admin/` (all tabs) and
   `clx/app/templates/cotton/admin/tabs.html`.
3. `clx/app/selectors/user.py` (`USER_LEVELS`, `user_level`,
   `user_search`, and friends exist only for the users tab).
4. `clx/app/tests/test_admin_api.py`.

## Shared-file edits

5. `clx/app/urls.py`: delete `admin_view_patterns`,
   `admin_api_patterns`, their two splices, and the admin imports.
6. `clx/app/services/user.py`: delete `LEVEL_GROUPS` and
   `user_level_set` and the selector imports; keep `user_create`,
   `user_update`, and `user_delete`.
7. `clx/app/templates/cotton/nav.html`: delete the
   `perms.app.manage_admin` Admin link block.
8. `clx/app/templates/pages/demos/index.html`: delete the Admin tile
   (it reverses `{% url 'admin' %}`, which no longer exists —
   leaving it 500s the launcher).
9. `clx/app/tests/test_csp.py`: drop `admin_view_patterns` from
   the import and the pattern iteration, and the Developer group
   setup if nothing gated remains.
10. `clx/app/tests/test_user.py`: delete the level and search
    tests (they exercised the users tab); keep the create, update,
    and delete coverage.

Prune CLAUDE.md's admin-surface mentions (the Permissions section's
worked examples and the admin users list references — grep for
`admin`), then run the verify suite. No models were removed.
