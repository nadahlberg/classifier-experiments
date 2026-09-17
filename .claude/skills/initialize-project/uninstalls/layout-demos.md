# Uninstall the layout demos

Removes the four pages that exist only to show a layout: dashboard,
card, card grid, and content. The layouts themselves stay — real
pages extend them — and so do the demos launcher, the components
page, and the markdown demo, which are permanent fixtures.

## Remove

1. `clx/app/urls.py`: the `card/`, `card-grid/`, `content/`,
   and `dashboard/` entries in `demos_view_patterns`.
2. The `card`, `card_grid`, `content`, and `dashboard` views in
   `clx/app/views/demos.py`.
3. `clx/app/templates/pages/demos/card.html`,
   `card_grid.html`, `content.html`, and `dashboard.html`.
4. The four "Layout:" tiles in
   `clx/app/templates/pages/demos/index.html`.
5. Grep the tests for `demos-card`, `demos-content`, and
   `demos-dashboard` and prune what surfaces; the tests that
   iterate `demos_view_patterns` adjust themselves.

Run the verify suite.
