# Layouts

Layouts use Django inheritance, not components — blocks are the right tool
for "the page fills in the holes" — and every layout extends one root.

## base.html

[`layouts/base.html`](sym:ab759c4507d6+) is the HTML skeleton and the most
primitive layout: the `<head>` (stylesheet, the compiled JS bundle loaded
*before* Alpine, favicon, manifest and PWA meta tags, with the title
defaulting to the configured site name), then the `nav`, `content`,
`footer`, `extra_head` and `extra_body` blocks. `nav` and `footer` are
opt-in — empty by default, so a page or layout that wants chrome says so.
The `<c-messages />` toast stack mounts on every page.

Its script block declares the two helpers every other block in the bundle
can call (the bundle shares one top-level scope): `csrfToken()`, and
`api(url, {method, body})` — the one HTTP path for all frontend requests.
`api` attaches the CSRF header on non-GET, JSON-encodes anything that is
not `FormData` (which must pass through untouched or the browser cannot
set the multipart boundary), and throws an `Error` whose message is the
`{"message", "extra"}` body [`ApiErrorMiddleware`](../request/errors.md)
renders — so a call site is a `try`/`catch` over `error.message`. The
same block registers the service worker, which is what makes every page
PWA-capable.

## The three page frames

[`layouts/card.html`](sym:fceea53232c5+) centers a single card on a bare
nav — the frame for login, signup and every other allauth page, exposing a
`card` block. [`layouts/card_grid.html`](sym:628159436f9d+) is the
dashboard frame: full nav, `heading`/`subheading`, and a `cards` block of
stacked sections. [`layouts/content.html`](sym:888917ad007f+) is the prose
frame: marketing nav and footer, a `.content` article with
`heading`/`subheading`/`sections` blocks, and a sticky table of contents.

The table of contents is the `toc` Alpine component declared in the same
file: it scans `.content` for `h2[id]`/`h3[id]`, builds a two-level group
list, tracks the visible section with an `IntersectionObserver`, and
appends a copy-link button to each heading. A `MutationObserver` re-scans
on any change to the prose — batched through `requestAnimationFrame`, and
disconnected during its own DOM writes so the copy-link decoration does
not trigger another rescan — which is what lets the TOC follow a live
markdown preview as it is typed.

## The application frame

[`layouts/three_panel.html`](sym:f780c270292b+) is the full-height
app-surface frame (chat, search, the codebase explorer): a left panel, a
toolbar row over the center, and an optional right panel, with `left`,
`toolbar`, `center`, `right` and the toggle-button blocks as the holes.
Its `panels` component holds the two booleans; on small screens the panels
become fixed overlays with slide transitions, closed by `@click.outside`,
while `sm:`/`lg:` utilities pin them static on wider screens. The height
comes from `h-[calc(100dvh-var(--spacing-nav))]`, so the frame and the nav
move together through one token.
