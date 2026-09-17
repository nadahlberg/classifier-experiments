# Errors

Business-rule failures are raised, not returned: a service raises
[`ApplicationError`](sym:efd1a2c8f209+) with a message and an optional
`extra` dict, the exception bubbles through the endpoint untouched, and one
middleware renders it. Unexpected errors are never caught anywhere — they
keep Django's normal 500 path (and reach Sentry when configured).

## The exception family

Three subclasses add a `status_code` so the same rendering produces the
right HTTP semantics: [`AuthenticationError`](sym:f8db50aa8411+) (401),
[`PermissionDeniedError`](sym:6973f4ff158e+) (403), and
[`RateLimitError`](sym:0d1c8bf35e49+) (429), which also carries
`retry_after` seconds for the header. Everything else renders as 400.

## ApiErrorMiddleware

[`ApiErrorMiddleware`](sym:768336ab6046+) sits last in `MIDDLEWARE` (so its
`process_exception` runs first) and renders two exception types as
`{"message", "extra"}` JSON: `ApplicationError` with the subclass's status
and a `Retry-After` header when the error carries one, and Django's
`ValidationError` as a 400 whose `extra.fields` maps field names to
messages — which is how a service's `full_clean()` failure reaches a JSON
client without the endpoint doing anything.

It only applies to API views: [`_is_api_view`](sym:7db2b832f4c4+) accepts a
view whose module lives under [the `api` package](sym:ff8ffeffd52e) or that
carries the `api_view` attribute `api_auth` stamps (which is how the test
suite's throwaway endpoints, defined outside `api/`, still get JSON
errors). HTML views keep Django's normal error pages, rendered from the
templates in `template_overrides/`.

## Body parsing

The parsing helpers raise the same way, so malformed input is
indistinguishable in shape from a business failure:
[`parse_body`](sym:a6640b0aa43a+) tolerates an empty body (returns `{}`) but
rejects non-JSON and non-object bodies, and
[`parse_int`](sym:233c193a38ea+) / [`parse_float`](sym:ee4ec8798997+) read
optional numeric fields with defaults, naming the offending key in the
error. An endpoint that parses, calls a service and returns needs no error
handling of its own at any step.
