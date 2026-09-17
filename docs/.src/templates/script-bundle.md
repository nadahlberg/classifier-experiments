# The script bundle

Every line of the project's JavaScript lives in `{% script %}` blocks at
the bottom of the templates that own the behaviour, and ships as one
compiled file, `static/js/main.js`. The tag is a compile-time marker: the
browser never sees a block, only the bundle.

## The tag

[The `script` tag](sym:e062cc881b17+,4f9a779ccf81) parses to
[a node that renders nothing](sym:9e4f76285128+). It raises
`TemplateSyntaxError` at render time for a block containing template nodes
(Django values cross into JavaScript as data attributes, never
interpolation) or one not wrapped in
[real `<script>` tags](sym:b6f6783a5ff7) — the wrapper is what keeps an
editor highlighting the body as JavaScript. Both rejections are pinned by
tests ([template syntax](sym:69dc33dd3845+),
[bare content](sym:aa797e2566ea+)), as is
[the render-nothing contract](sym:cc770f2c2378+).

## The collector

[`scripts_collect`](sym:01dc453a9795+) walks [the template
directories](sym:493d4537b3f7) in `TEMPLATES["DIRS"]` order, extracts
every block with [`scripts_bodies`](sym:a913fc2be2fb+) — which re-applies
the same two rejections, because the collector sees templates nothing
rendered ([`SCRIPT_BLOCK`](sym:d35ecec60734) finds the blocks, and a `{%`
or `{{` inside one is an error there too, [also
tested](sym:ea6880f164ba+,cf4e8fcb80a1)) — and concatenates each body under
a `/* origin */` comment into [the bundle
path](sym:e829cc640fdf,073ad6183c21). The collector reads files, not
renders, so a primitive used twelve times contributes its registration
once, and [every tag in a multi-block template is
collected](sym:f7a3fee842f3+).

Because the bundle is one script sharing one top-level scope, the
collector is also where name collisions are caught:
[a second `Alpine.data`/`Alpine.store` registration of the same
name](sym:b46dfbb377f1) fails the build ([test](sym:18e265ce700c+) — but
[merely *reading* a store is not a registration](sym:d3e7d002b59b+)), and
[a duplicate top-level declaration](sym:f2951c202e1d) fails it too
([test](sym:26ccd8cd516e+)) — the second check matters more than it looks,
because a duplicate `const` is a `SyntaxError` that stops the whole bundle
parsing on every page. The declaration regex knows
[`async function` counts](sym:9d46da98ed64+) and
[an indented declaration does not](sym:70fe3e9ddbe2+).

The integration pin: [every registration named in the templates is
present in a freshly compiled bundle](sym:d2c9212527eb+,ba3fa4cf0986,e2de6c128c89).

## The command

[`manage collectscripts`](sym:1b9b1cc6ce76+) is the thin interface: one-shot
by default (a collection error becomes a fatal `CommandError` —
[tested](sym:0859a27350f9+) — which is what fails the Docker build on a bad
block), and `--watch` recompiles on any template change, staying alive
through errors so a typo mid-edit prints rather than kills the watcher.
The `scripts` compose service runs the watcher in dev; the Dockerfile runs
the one-shot at build, exactly like the Tailwind CSS build. `main.js` is a
gitignored build artifact.

Validation therefore happens twice on purpose: the tag raises while a page
renders (immediate, in front of you), the collector raises for templates
nothing rendered.
