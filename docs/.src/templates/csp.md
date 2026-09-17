# CSP and Alpine

The app enforces a strict Content-Security-Policy — `script-src 'self'`,
no nonce, no `unsafe-inline`, no `unsafe-eval` — and everything about how
the frontend is written follows from it.

## The policy

[`CONTENT_SECURITY_POLICY`](sym:99112da2bedd) locks every directive to
`'self'` (plus `blob:` for images and media), with `object-src` and
`frame-ancestors` at `'none'`. `form-action` is deliberately absent:
Chrome enforces it against the redirect *target* of a form submission, and
the OAuth authorize form 302s to the client's redirect URI after POST, so
any value written there would break MCP client authorization —
[the strictness test pins the omission along with the rest of the
header](sym:6a1bcc6b8792).

With S3 on, static files come from the bucket instead of `'self'`, so
[`static_sources`](sym:435f4ad36c87,965a9714515d) widens exactly
`script-src`, `style-src` and `img-src` with one value built from
[the endpoint](sym:08881799993b,ff87fac94ebb) and [the public
bucket](sym:bcd5ece68d13,332cad2b49eb) — bucket path included, trailing
slash included, because Spaces puts every tenant on one regional host and
a bare host would let any other customer's bucket serve scripts into our
pages. Three tests pin this: [the bucket is an allowed
source](sym:8c307a17c5c7+,9879d855583b,4efa9e555969), [the source is scoped
to the bucket path](sym:b09b18842dc5+), and [without S3 the policy stays
strictly same-origin](sym:1c896d0c1ccd+).

[`frame_self`](../request/api-auth.md) is the one sanctioned relaxation:
the upload preview stream swaps `frame-ancestors` to `'self'` so our own
preview cards can iframe it, while the download response keeps `'none'` —
[both directions tested](sym:4b1070a5fd09+).

## No inline scripts, ever

The page renders zero inline scripts; behaviour ships in
[the compiled bundle](script-bundle.md), loaded before Alpine.
[A sweep test walks every routed page](sym:9b2839d41494+) — the page list
derived from the view pattern lists, so a new page joins by existing —
and asserts every `<script>` tag has a `src` or is an inert
`type="application/json"` data block: CSP governs execution, and
`json_script` is Django's documented way to hand request-time context to
JavaScript under a strict policy (the codebase explorer embeds its
inventory that way).

## The CSP build of Alpine

[The vendored `alpine.min.js`](sym:3f7673ffb5b3) is Alpine's CSP build,
whose evaluator resolves only property paths and method references — the
standard build compiles every directive expression with the `Function`
constructor, which needs `unsafe-eval` and turns any HTML injection into
code execution through the framework. [A test fingerprints the
build](sym:8570fe777e03,45d2a7328d13) by the error string only the CSP
build contains, so swapping the file for the standard build fails CI
instead of silently defeating the policy.

The grammar that build imposes — registered names in `x-data`, bare paths
in bindings, method references in handlers, no operators, no arguments,
no `x-model` — is machine-checked over every template by
[the parser in `app/scripts.py`](sym:681e7abc1b46+,019af314c3b6):
[`DIRECTIVE`](sym:5643eb965661) finds each directive,
[`_directive_error`](sym:6e14ab79c9d0+) judges the expression against
[the path grammar](sym:b59e89c9f72a), [the `x-for`
form](sym:77f4f0b0a152) and [the directives that take no
expression](sym:044b87b40963). The E501–E503 checks consume these
verdicts (see [The rule catalog](../conventions/rules.md)); the stakes
are that illegal expressions fail *silently* to empty, so without the
check nothing would crash when one slipped in. The replacements the
grammar forces — getters for computed bindings, enrichment at fetch time,
`:value` + `@input` instead of `x-model`, per-row arguments as data
attributes — are visible throughout
[the behavioural primitives](primitives.md).
