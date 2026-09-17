# Theming

The design system is a set of semantic tokens defined in the `@theme`
blocks of [`src/main.css`](sym:f999144cabf8), compiled by the standalone
Tailwind binary. Templates use roles, never raw palette colors —
`bg-primary`, not `bg-gray-900` — so a rebrand edits token definitions and
every primitive follows. `/demos/components/` renders the whole theme at
a glance and is the visual smoke test after any theme change.

## The tokens

Color roles come in pairs and triples: `primary`/`primary-hover`/
`primary-foreground` for actions (the `-foreground` is the text placed on
the fill); `secondary` defaulting to primary until a brand needs a second
color; `accent` for subtle emphasis fills, its foreground doubling as the
interactive-secondary text color; `background` versus `surface` — the same
value today, kept separate so off-white-page-with-white-cards is a
two-line change; `muted`, `foreground`, and the `border`/`border-strong`/
`ring` hairline set; the `inverse-*` trio for the dark surfaces (footer,
toasts, tooltips, code, the `<html>` backdrop behind overscroll); and the
four statuses, each with solid, `-soft` and `-soft-foreground` forms —
borders on soft tints use `border-current/25`, no extra token.

Beyond color: `--font-sans`/`--font-mono`/`--font-display` (display is the
heading face, defaulting to the sans stack), `--radius-control` versus
`--radius-surface` (buttons and inputs versus cards and modals), the two
card shadows as the only elevations, `--spacing-nav` (which yields
`h-nav`, `top-nav` and the full-height calc, so the nav and the
full-height layouts move together), and `--container-shell` for the shared
page width.

## Prose

`.content` is the one prose class, and markdown's output is its structural
contract: the element set it styles is exactly what the renderer can emit,
so a rendered document and a hand-written page are the same markup under
the same rules — which is why its selectors are descendant rather than
direct-child (markdown nests, and a `<p>` inside a `<blockquote>` must
still be styled). Non-prose markup inside `.content` opts out by carrying
its own utilities, which win because Tailwind orders utilities after
components. Spacing routes through `--prose-block-gap`,
`--prose-heading-gap` and `--prose-subheading-gap`, so a tighter variant
is a class that re-points three variables, not a second rule set. Heading
ids are what the content layout's table of contents reads; hand-written
pages write them by hand, and the markdown component emits them only when
asked (see [Design-system primitives](primitives.md)).

## Rebranding

The rebrand checklist is one pass: the `@theme` blocks; `site_name` on the
SiteConfig row; the hard-coded wordmark in `cotton/brand.html`; the icon
files in `static/icons/`; and the hardcoded hex that CSS variables cannot
reach — the `theme-color` meta in `base.html` and the
`background_color`/`theme_color` in the web manifest. Then load
`/demos/components/` and review everything at once; the tests described in
[Design-system primitives](primitives.md) force the icons and primitives
to actually appear there.
