# The script bundle

Every line of the project's JavaScript lives in `{% script %}` blocks at
the bottom of the templates that own the behaviour, and ships as one
compiled file, `static/js/main.js`. The tag is a compile-time marker: the
browser never sees a block, only the bundle.

## The tag

[The `script` tag](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templatetags/scripts.py#L19-L39) parses to
[a node that renders nothing](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/templatetags/scripts.py#L11-L15). It raises
`TemplateSyntaxError` at render time for a block containing template nodes
(Django values cross into JavaScript as data attributes, never
interpolation) or one not wrapped in
[real `<script>` tags](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/scripts.py#L12) — the wrapper is what keeps an
editor highlighting the body as JavaScript. Both rejections are pinned by
tests ([template syntax](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_scripts.py#L188-L193),
[bare content](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_scripts.py#L196-L199)), as is
[the render-nothing contract](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_scripts.py#L177-L185).

## The collector

[`scripts_collect`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/services/scripts.py#L17-L48) walks [the template
directories](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/scripts.py#L79-L82) in `TEMPLATES["DIRS"]` order, extracts
every block with [`scripts_bodies`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/scripts.py#L85-L101) — which re-applies
the same two rejections, because the collector sees templates nothing
rendered ([`SCRIPT_BLOCK`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/scripts.py#L11) finds the blocks, and a `{%`
or `{{` inside one is an error there too, [also
tested](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_scripts.py#L163-L174)) — and concatenates each body under
a `/* origin */` comment into [the bundle
path](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/services/scripts.py#L13). The collector reads files, not
renders, so a primitive used twelve times contributes its registration
once, and [every tag in a multi-block template is
collected](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_scripts.py#L45-L63).

Because the bundle is one script sharing one top-level scope, the
collector is also where name collisions are caught:
[a second `Alpine.data`/`Alpine.store` registration of the same
name](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/scripts.py#L13-L15) fails the build ([test](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_scripts.py#L66-L82) — but
[merely *reading* a store is not a registration](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_scripts.py#L202-L223)), and
[a duplicate top-level declaration](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/scripts.py#L16-L20) fails it too
([test](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_scripts.py#L85-L102)) — the second check matters more than it looks,
because a duplicate `const` is a `SyntaxError` that stops the whole bundle
parsing on every page. The declaration regex knows
[`async function` counts](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_scripts.py#L105-L126) and
[an indented declaration does not](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_scripts.py#L129-L145).

The integration pin: [every registration named in the templates is
present in a freshly compiled bundle](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_scripts.py#L21-L42).

## The command

[`manage collectscripts`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/management/commands/collectscripts.py#L11-L41) is the thin interface: one-shot
by default (a collection error becomes a fatal `CommandError` —
[tested](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_scripts.py#L226-L244) — which is what fails the Docker build on a bad
block), and `--watch` recompiles on any template change, staying alive
through errors so a typo mid-edit prints rather than kills the watcher.
The `scripts` compose service runs the watcher in dev; the Dockerfile runs
the one-shot at build, exactly like the Tailwind CSS build. `main.js` is a
gitignored build artifact.

Validation therefore happens twice on purpose: the tag raises while a page
renders (immediate, in front of you), the collector raises for templates
nothing rendered.
