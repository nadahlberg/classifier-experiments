# CSP and Alpine

The app enforces a strict Content-Security-Policy — `script-src 'self'`,
no nonce, no `unsafe-inline`, no `unsafe-eval` — and everything about how
the frontend is written follows from it.

## The policy

[`CONTENT_SECURITY_POLICY`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L67-L83) locks every directive to
`'self'` (plus `blob:` for images and media), with `object-src` and
`frame-ancestors` at `'none'`. `form-action` is deliberately absent:
Chrome enforces it against the redirect *target* of a form submission, and
the OAuth authorize form 302s to the client's redirect URI after POST, so
any value written there would break MCP client authorization —
[the strictness test pins the omission along with the rest of the
header](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_csp.py#L24-L44).

With S3 on, static files come from the bucket instead of `'self'`, so
[`static_sources`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L61-L65) widens exactly
`script-src`, `style-src` and `img-src` with one value built from
[the endpoint](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L59) and [the public
bucket](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L60) — bucket path included, trailing
slash included, because Spaces puts every tenant on one regional host and
a bare host would let any other customer's bucket serve scripts into our
pages. Three tests pin this: [the bucket is an allowed
source](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_csp.py#L142-L156), [the source is scoped
to the bucket path](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_csp.py#L159-L175), and [without S3 the policy stays
strictly same-origin](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_csp.py#L178-L192).

[`frame_self`](../request/api-auth.md) is the one sanctioned relaxation:
the upload preview stream swaps `frame-ancestors` to `'self'` so our own
preview cards can iframe it, while the download response keeps `'none'` —
[both directions tested](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_csp.py#L91-L117).

## No inline scripts, ever

The page renders zero inline scripts; behaviour ships in
[the compiled bundle](script-bundle.md), loaded before Alpine.
[A sweep test walks every routed page](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_csp.py#L48-L87) — the page list
derived from the view pattern lists, so a new page joins by existing —
and asserts every `<script>` tag has a `src` or is an inert
`type="application/json"` data block: CSP governs execution, and
`json_script` is Django's documented way to hand request-time context to
JavaScript under a strict policy (the codebase explorer embeds its
inventory that way).

## The CSP build of Alpine

[The vendored `alpine.min.js`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/static/js/alpine.min.js) is Alpine's CSP build,
whose evaluator resolves only property paths and method references — the
standard build compiles every directive expression with the `Function`
constructor, which needs `unsafe-eval` and turns any HTML injection into
code execution through the framework. [A test fingerprints the
build](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_csp.py#L120-L129) by the error string only the CSP
build contains, so swapping the file for the standard build fails CI
instead of silently defeating the policy.

The grammar that build imposes — registered names in `x-data`, bare paths
in bindings, method references in handlers, no operators, no arguments,
no `x-model` — is machine-checked over every template by
[the parser in `app/scripts.py`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/scripts.py#L63-L76):
[`DIRECTIVE`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/scripts.py#L22) finds each directive,
[`_directive_error`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/scripts.py#L40-L60) judges the expression against
[the path grammar](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/scripts.py#L23), [the `x-for`
form](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/scripts.py#L24-L28) and [the directives that take no
expression](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/scripts.py#L29). The E501–E503 checks consume these
verdicts (see [The rule catalog](../conventions/rules.md)); the stakes
are that illegal expressions fail *silently* to empty, so without the
check nothing would crash when one slipped in. The replacements the
grammar forces — getters for computed bindings, enrichment at fetch time,
`:value` + `@input` instead of `x-model`, per-row arguments as data
attributes — are visible throughout
[the behavioural primitives](primitives.md).
