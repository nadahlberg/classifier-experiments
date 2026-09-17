---
name: rebrand
description: Establish a new brand identity and reskin the whole app - absorb reference material or interview the user into a brand spec, then apply it across every touchpoint - theme tokens, fonts, wordmark, icons, manifest, site name - rebuild the landing page in the new voice, and add the components the project's use case will need. Use when the user wants to rebrand, reskin, re-theme, pick a visual identity, or build out the landing page.
argument-hint: [the brand idea, reference files, or nothing]
---

# Rebrand the app

This template ships deliberately unbranded: gray-on-white tokens, a
text wordmark that says the project's name, a monogram favicon, a
one-hero landing page. This skill replaces all of it with a real
identity. It usually runs right after initialize-project, but nothing
requires that — it works any time the user wants the app to stop
looking like the template.

`$ARGUMENTS` may carry the idea, paths to reference material, or
nothing. The skill has two halves: **decide** the brand (stages 1–2)
and **apply** it (stages 3–4). Some users only want the first half —
a talked-through spec is a complete deliverable — so confirm scope up
front and stop where the user's interest stops. When the
AskUserQuestion tool is available, put every decision through it with
your recommendation first, labeled "(Recommended)".

## The touchpoint map

Every place a brand lives in this codebase. Stage 3 walks these in
order; nothing else in the repo carries brand:

| Touchpoint | File(s) | What it holds |
| --- | --- | --- |
| Theme tokens | `clx/app/src/main.css` `@theme` blocks | colors, fonts, radii, shadows — the whole visual system; everything else uses roles |
| Fonts | `static/fonts/` (create it) + `@font-face` in `main.css` | self-hosted woff2; CSP blocks font CDNs |
| Wordmark | `templates/cotton/brand.html` | hard-coded on purpose — a real brand replaces it with its own mark |
| Icons | `static/icons/` — `favicon.svg`, `apple-touch-icon.png` (180, opaque), `icon-192.png`, `icon-512.png` (maskable) | every file here must be named on `/demos/components/` (guard test) |
| Hardcoded hex | `theme-color` meta in `layouts/base.html`; `background_color` / `theme_color` in `pages/manifest.webmanifest` | match to `inverse-surface` / `background`; CSS variables can't reach these |
| Site name | `models/site_config.py` default + the live `SiteConfig` row | titles, footer, manifest all read `site_config.site_name` |
| Landing page | `pages/index.html` + components under `cotton/index/` | the marketing surface |
| Component library | `pages/demos/components.html` | the theme's visual smoke test; new root primitives must be documented here (guard test) |

Deliberately downstream, touched by nothing: the nav, footer, account
pages, error pages, and email templates all read tokens and
`site_config` — they rebrand themselves.

## Stage 1 — Gather

Two intake channels, freely mixed. Use whichever the user offers and
fill the gaps with the other.

**Reference material.** The user may hand over anything: another
project's repo, a single HTML file, a CSS file, screenshots, a live
URL, a brand guide PDF, a logo file. Read all of it before asking
anything — a question the material answers is a wasted round-trip.
Extract and map into this repo's vocabulary:

- **Colors** → the token roles. Identify the action color (primary),
  any second brand color (secondary), surface/background treatment
  (same value, or off-white page with white cards?), text hierarchy,
  border weight, and the dark inverse surface. Note exact values.
- **Typography** → face names, weights actually used, whether
  headings use a different face (`--font-display`).
- **Shape and depth** → corner radii on controls vs. cards, shadow
  personality (flat, soft, pronounced).
- **Voice** → how the copy talks: sentence length, capitalization,
  humor, jargon level. This drives the landing page as much as the
  colors do.
- **Layout patterns** worth stealing for the landing page.

**Interview.** For whatever the material didn't settle, run rounds
the way the spec skill does — ask the current frontier, wait, ask
what it unblocked. Design questions deserve concrete options, not
essay prompts: offer 3–4 curated directions with real values
("Forest — primary emerald-800 on warm white, serif display face"),
never "what colors do you want?". The usual frontier, first round:

1. **Identity** — confirm the name (it may differ from the repo
   slug's display name), a one-line what-it-is, and who it's for.
   The audience shapes everything downstream.
2. **Personality** — two axes, each a pick: playful ↔ serious,
   warm ↔ technical. These make your later recommendations grounded
   instead of arbitrary.
3. **Color direction** — curated palettes fitting the personality.
4. **Typography** — curated pairings (display + body + mono), open
   licenses only since we self-host (Google Fonts' catalog is the
   safe pool to draw from).

Second round, once those land: shape/depth direction, the landing
page's job (collect a waitlist? drive sign-ups? explain a product?),
its section list, and which bespoke components the use case needs —
propose these yourself from what the product is (a SaaS wants a
pricing table and feature grid; a devtool wants a code-sample hero
and install snippet; a marketplace wants listing cards). Components
the user confirms get built in stage 3.

## Stage 2 — The spec

Write the settled brand to `local/brand.md` (scratch space — it
guides this run and doesn't ship). Exact values, no adjectives
without numbers:

- every `@theme` token that changes, name → new value;
- fonts: family, weights, file plan;
- wordmark and icon design (described precisely enough to draw);
- the two hardcoded hexes;
- voice notes — three or four rules a copywriter could follow;
- landing page outline: sections in order, each with its job and a
  first draft of its headline;
- the bespoke component list, each with its namespace
  (`cotton/index/…` vs. root primitive) and interface.

Show the user the spec and get sign-off. This is the last cheap
moment to change direction — and the natural end point for a user
who only wanted to talk it through.

## Stage 3 — Apply

Work the touchpoint map top to bottom. The dev watchers rebuild CSS
and the script bundle on change (`docker compose up -d` if not
running), so edits are visible live at http://localhost:8000.

### Tokens

Rewrite the `@theme` blocks in `src/main.css`. Rules:

- **Change values, never names.** Templates, component classes, and
  tests all speak the role names; a renamed token is a rebrand of
  the codebase, not the brand.
- Set every role deliberately, including the ones that keep their
  template value — the spec said so, the file should agree.
  `secondary` stays equal to `primary` unless the brand has a real
  second color.
- Derive, don't guess: `-hover` is a step of the same hue;
  `-foreground` must actually read on its fill (check contrast —
  4.5:1 for text-bearing pairs like `primary-foreground` on
  `primary` and each `-soft-foreground` on its `-soft`); status
  colors can shift hue toward the palette's temperature but must
  stay recognizably green/amber/red/blue.
- `background` vs. `surface` is a real decision now: an off-white
  page with white cards is exactly what the split exists for.
- Radii and shadows carry as much personality as color — a brand
  rarely changes hue but keeps the template's 1rem cards.

### Fonts

The CSP pins `font-src` and `style-src` to `'self'`, so a Google
Fonts `<link>` is blocked by design. Self-host instead:

1. Fetch woff2 files — request the family's CSS with a modern
   browser User-Agent and download the woff2 URLs it lists:
   `curl -A "Mozilla/5.0 ... Chrome/120" "https://fonts.googleapis.com/css2?family=<Family>:wght@400;600;700"`.
   Only the weights the spec names; each weight is page weight.
2. Put them in `clx/app/static/fonts/`, add `@font-face` rules
   (with `font-display: swap`) at the top of `main.css`, and point
   `--font-sans` / `--font-display` / `--font-mono` at them, real
   fallback stacks included.

### Wordmark and icons

- `cotton/brand.html` — replace the text link's content with the
  new mark: styled text, inline SVG, or an `<img>` from
  `static/icons/`. It is hard-coded rather than reading `site_name`
  on purpose; keep it that way.
- Redraw `static/icons/favicon.svg` to the spec.
- Regenerate the PNGs from it: `apple-touch-icon.png` at 180×180
  with an opaque background (iOS composites transparency onto
  black), `icon-192.png` and `icon-512.png` as maskable — keep the
  mark inside the central 80% safe zone since launchers crop to
  circles. Rasterize with the first available of `rsvg-convert`,
  `inkscape`, or `uv run --with cairosvg python -c ...`; if none
  can be had, ask the user to export the three sizes and drop them
  in.
- The Logos section of `/demos/components/` names every file in
  `static/icons/` — a test fails if an added or renamed asset isn't
  documented there.

### Hardcoded hex and site name

- `theme-color` meta in `layouts/base.html` → the new `background`
  hex; `background_color` in `pages/manifest.webmanifest` → the new
  `inverse-surface` hex; its `theme_color` → `background`.
- If the brand name differs from the current site name: change the
  default on `models/site_config.py`, `uv run manage makemigrations`,
  and update the live row through the service —
  `uv run manage shell -c "from clx.app.services.site_config import site_config_update; site_config_update(site_name='<Name>')"` —
  so the running app and a fresh database agree.

### Landing page

Rebuild `pages/index.html` to the spec's outline. This is a real
page in the new voice, not a template with the nouns swapped:

- It extends `layouts/base.html` with the marketing nav and footer,
  like the current one. Section components live in `cotton/index/`
  — page-owned namespace, inheriting context, no `<c-vars>`
  ceremony required.
- Write real copy from the voice notes. Where a fact is missing (a
  price, a customer name, a screenshot), say so and ask — a
  plausible invented testimonial is worse than a placeholder the
  user knows to replace.
- All the CSP/Alpine rules apply: no inline scripts, behaviour in
  `{% script %}` blocks in the component that owns it, directive
  expressions within the CSP-build grammar. A landing page rarely
  needs any of it — prefer CSS-only treatments.
- Imagery without assets: gradients, grids, and geometry from the
  token palette (the current hero's technique) scale better than
  stock placeholders.

### Bespoke components

Build the confirmed list. Placement follows the house rule — start
in `cotton/index/`, promote to root only when a second surface needs
it or the user asks for a design-system primitive. A root primitive
must declare `<c-vars>`, take `only`, and gets a documented section
with an `id="<name>"` anchor on `/demos/components/` — the guard
test fails the build without one, which is the forcing function, not
a chore.

## Stage 4 — Review and verify

1. Run the checks: `uv run --extra dev pytest`,
   `uv run --extra dev mypy clx`,
   `uv run pre-commit run --all-files` (stage new files first —
   `git add -A` — or the hooks skip them). The rebrand-sensitive
   tests are `test_components.py` (undocumented primitives or
   icons) and `test_csp.py` (an inline script or remote source that
   slipped in); the collectscripts build catches script-name
   collisions from new components.
2. Tell the user to review two pages while signed in:
   `/demos/components/` — every token and primitive under the new
   theme at once, the whole point of the page — and `/` for the
   landing page. Walk their feedback back into the spec and the
   files; small rounds are normal, a rebrand converges by looking.
3. Leave everything uncommitted and point the user at the shipit
   skill. Suggest `local/brand.md` is worth keeping around for the
   next design conversation, even though it never ships.
