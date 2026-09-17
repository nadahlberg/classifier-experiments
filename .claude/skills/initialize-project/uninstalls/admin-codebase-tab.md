# Uninstall the admin Codebase tab

Removes the codebase explorer's admin surface: the tab, its page, and
the inventory cards behind it. Start from
`grep -rn "codebase" clx/app` and follow what you find rather
than trusting the list below to be complete. No models are involved,
so no migration reset.

**`clx/app/selectors/codebase.py` stays.** The pattern checks
(`manage check`, the `checks` CI job) run over the fact tables its
extractor builds, so the module is checks machinery now, not explorer
code — only its `_Inventory` half (the cards) belongs to this tab.
Also keep: `clx/app/scripts.py` and
`clx/app/services/scripts.py` (the `collectscripts` build), and
the `api_auth` config stash and `busts_cache` key stash with their
tests (`test_api_auth_exposes_its_config`,
`test_busts_cache_exposes_its_keys`) — those are the layers' own
contracts, and the checks read the `api_auth` stash too.

## Remove

1. `clx/app/templates/pages/admin/codebase.html` and the whole
   `clx/app/templates/cotton/admin/codebase/` directory.
2. The `codebase` view in `clx/app/views/admin.py` (and its
   `codebase_inventory` import).
3. The `path("codebase/", ...)` entry in `admin_view_patterns` in
   `clx/app/urls.py`.
4. The Codebase `<a>` block in
   `clx/app/templates/cotton/admin/tabs.html`.
5. In `clx/app/selectors/codebase.py`: the `_Inventory` class,
   `codebase_inventory`, and the card helpers only `_Inventory` uses
   (`_chip`, `_ref`, the `build_*` methods' private helpers) — keep
   `_Extractor`, the fact dataclasses, and `codebase_facts`. Confirm
   with the verify suite that nothing the checks import was removed.
6. In `clx/app/tests/test_codebase.py`: the inventory and page
   tests; keep any test that pins `codebase_facts` extraction the
   checks rely on (or delete the file if none remain after the split).

Run the verify suite.
