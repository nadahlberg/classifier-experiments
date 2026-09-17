# Design-system primitives

Components at the root of `cotton/` are the design system; anything nested
belongs to a single page or surface. Every root primitive declares its
interface with `<c-vars>` (rule E407), styles itself entirely in semantic
tokens (see [Theming](theming.md)), and is documented on
`/demos/components/` — [a test renders that page and asserts every root
component has a section anchor](sym:ed50457713ab+), because cotton only
compiles a component when a page renders it, so a primitive missing from
the library page could ship broken and fail on whichever page reaches for
it first. [The `CHROME` set](sym:0fd50cf559bb,8d27a7a0d0e4) excludes the
app furniture — nav, footer, messages — which lives at the root because
every layout uses it, not because it is a design-system part. [A sibling
test](sym:95d9b882ae2c+,f12b5935254f) holds the brand image assets in
[`static/icons/`](sym:0bdf5352c125,022541318d7b,ca132b8eb5e8,af3eefa3aad8)
— favicon, apple-touch icon, the two PWA icons — to the same rule: each
must be named on the components page's Logos section, so a rebrand sees
every asset in one place.

## Static pieces

[`button`](sym:b369cce37333+) renders an `<a>` when given `href` and a
`<button>` otherwise, with variant (primary, outline, ghost, danger) and
size axes. [`badge`](sym:ec4b3002d925+) and [`alert`](sym:43218673aa49+)
map a status color onto the `-soft` token pairs, alerts adding an optional
title. [`avatar`](sym:127c2114144b+) shows the first letter of a name in
three sizes. [`field`](sym:06171978d80a+) is the labelled input with help
and error slots — error styling wins over help text.
[`spinner`](sym:29085f3c70d3+) and [`tooltip`](sym:b0191d8f9d61+) are pure
CSS (the tooltip is a hover-revealed span positioned by a `position` var).
[`card_grid`](sym:3cb51380cd72+) is the responsive grid and
[`card_section`](sym:1d9d104817c7+) a titled wrapper around it.
[`brand`](sym:c3d378a76790+) is the deliberately hard-coded wordmark — a
real brand replaces this component with its own logo, which is why it does
not read `site_config.site_name`. [`footer`](sym:e057182c11cc+) is the
inverse-surface strip with the copyright line (which *does* read the site
name). [`dropdown_item`](sym:e2f9ea82a7a1+) is the flat sub-part of the
dropdown — root-level with the parent's name as a prefix, never nested,
so the components-page guard covers it too.

## Behavioural pieces

Each of these owns an Alpine island whose factory is declared in the same
file's script block, following every CSP-build rule: declared properties
with defaults, getters for computed bindings, config via data attributes.

[`dropdown`](sym:9c10d6656f19+) is the open/close/toggle triple with
click-outside and escape handling. [`modal`](sym:f3db2f684895+) teleports
its panel to `<body>` (so the listener for `modal-close` sits on the
teleported wrapper with `.stop` — teleported DOM does not bubble through
the component root), locks body scroll while open via `$watch`, and
supports type-to-confirm: pass `confirm="phrase"` and the `blocked` getter
gates the confirm button until the challenge matches.
[`toggle`](sym:d7bb22cc4d5d+) is a switch whose initial state arrives as
`data-checked` and whose hidden input mirrors the state for form posts.
[`textarea`](sym:4d01e3882703+) auto-fits its height on input and window
resize. [`messages`](sym:8c0188f727ff+) renders Django messages as toasts
that enter on the next tick and auto-dismiss after four seconds, the drain
ring colored by message level. [`markdown`](sym:0d50c98a064b+) is the
client-side renderer: a `.content` div whose `x-html` binds to the
rendered output, with the whole renderer — a line-based parser for
headings, lists, fences, quotes, tables and rules — living in its script
block. It emits heading ids only when the caller passes `ids`
(`data-ids`), because an embedded preview that emitted ids would put its
headings in the host page's table of contents and collide with the host's
anchors; the default covers the safe case.

[`nav`](sym:fef0961440ed+) is the chrome with three variants — `dashboard`
(default: full-width, Demos link, account dropdown with profile, admin for
`perms.app.manage_admin` holders, and a signed logout form), `marketing`
(shell-width, Get started button), and `bare` (brand only, no border, used
by the card layout). A spacer div matches the fixed nav's height except in
`bare`.
