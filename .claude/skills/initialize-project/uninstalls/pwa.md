# Uninstall the PWA

Removes installability: the manifest, the service worker, and the
install icons. General branding stays — the favicon, the theme-color
meta, and the apple-touch-icon serve any site, not just an
installable one.

## Remove

1. `clx/app/urls.py`: delete `pwa_patterns` and its
   `*pwa_patterns` splice.
2. `clx/app/templates/pages/sw.js` and
   `clx/app/templates/pages/manifest.webmanifest`.
3. In `clx/app/templates/layouts/base.html`: the manifest `<link>`, the
   `mobile-web-app-capable`, `apple-mobile-web-app-capable`,
   `apple-mobile-web-app-status-bar-style`, and
   `apple-mobile-web-app-title` metas, and the `serviceWorker`
   registration block inside `{% script %}` (keep `csrfToken` and
   `api`).
4. `clx/app/static/icons/icon-192.png` and `icon-512.png`, and
   their entries in the Logos section of
   `clx/app/templates/pages/demos/components.html`.
5. `clx/settings.py`: delete the `worker-src` and
   `manifest-src` CSP directives.
6. Grep the tests for `manifest` and `service-worker` and prune
   what surfaces.

Prune CLAUDE.md's service-worker and manifest mentions (the
Templates section and the rebrand checklist), then run the verify
suite.
