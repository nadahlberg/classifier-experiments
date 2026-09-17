# Design-system primitives

Components at the root of `cotton/` are the design system; anything nested
belongs to a single page or surface. Every root primitive declares its
interface with `<c-vars>` (rule E407), styles itself entirely in semantic
tokens (see [Theming](theming.md)), and is documented on
`/demos/components/` — [a test renders that page and asserts every root
component has a section anchor](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_components.py#L15-L42), because cotton only
compiles a component when a page renders it, so a primitive missing from
the library page could ship broken and fail on whichever page reaches for
it first. [The `CHROME` set](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_components.py#L11) excludes the
app furniture — nav, footer, messages — which lives at the root because
every layout uses it, not because it is a design-system part. [A sibling
test](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_components.py#L46-L66) holds the brand image assets in
[`static/icons/`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/static/icons/favicon.svg)
— favicon, apple-touch icon, the two PWA icons — to the same rule: each
must be named on the components page's Logos section, so a rebrand sees
every asset in one place.

## Static pieces

[`button`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/button.html) renders an `<a>` when given `href` and a
`<button>` otherwise, with variant (primary, outline, ghost, danger) and
size axes. [`badge`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/badge.html) and [`alert`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/alert.html)
map a status color onto the `-soft` token pairs, alerts adding an optional
title. [`avatar`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/avatar.html) shows the first letter of a name in
three sizes. [`field`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/field.html) is the labelled input with help
and error slots — error styling wins over help text.
[`spinner`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/spinner.html) and [`tooltip`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/tooltip.html) are pure
CSS (the tooltip is a hover-revealed span positioned by a `position` var).
[`card_grid`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/card_grid.html) is the responsive grid and
[`card_section`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/card_section.html) a titled wrapper around it.
[`brand`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/brand.html) is the deliberately hard-coded wordmark — a
real brand replaces this component with its own logo, which is why it does
not read `site_config.site_name`. [`footer`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/footer.html) is the
inverse-surface strip with the copyright line (which *does* read the site
name). [`dropdown_item`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/dropdown_item.html) is the flat sub-part of the
dropdown — root-level with the parent's name as a prefix, never nested,
so the components-page guard covers it too.

## Behavioural pieces

Each of these owns an Alpine island whose factory is declared in the same
file's script block, following every CSP-build rule: declared properties
with defaults, getters for computed bindings, config via data attributes.

[`dropdown`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/dropdown.html) is the open/close/toggle triple with
click-outside and escape handling. [`modal`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/modal.html) teleports
its panel to `<body>` (so the listener for `modal-close` sits on the
teleported wrapper with `.stop` — teleported DOM does not bubble through
the component root), locks body scroll while open via `$watch`, and
supports type-to-confirm: pass `confirm="phrase"` and the `blocked` getter
gates the confirm button until the challenge matches.
[`toggle`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/toggle.html) is a switch whose initial state arrives as
`data-checked` and whose hidden input mirrors the state for form posts.
[`textarea`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/textarea.html) auto-fits its height on input and window
resize. [`messages`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/messages.html) renders Django messages as toasts
that enter on the next tick and auto-dismiss after four seconds, the drain
ring colored by message level. [`markdown`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/markdown.html) is the
client-side renderer: a `.content` div whose `x-html` binds to the
rendered output, with the whole renderer — a line-based parser for
headings, lists, fences, quotes, tables and rules — living in its script
block. It emits heading ids only when the caller passes `ids`
(`data-ids`), because an embedded preview that emitted ids would put its
headings in the host page's table of contents and collide with the host's
anchors; the default covers the safe case.

[`nav`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templates/cotton/nav.html) is the chrome with three variants — `dashboard`
(default: full-width, Demos link, account dropdown with profile, admin for
`perms.app.manage_admin` holders, and a signed logout form), `marketing`
(shell-width, Get started button), and `bare` (brand only, no border, used
by the card layout). A spacer div matches the fixed nav's height except in
`bare`.
