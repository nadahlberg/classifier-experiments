# Errors

Business-rule failures are raised, not returned: a service raises
[`ApplicationError`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/exceptions.py#L4-L10) with a message and an optional
`extra` dict, the exception bubbles through the endpoint untouched, and one
middleware renders it. Unexpected errors are never caught anywhere — they
keep Django's normal 500 path (and reach Sentry when configured).

## The exception family

Three subclasses add a `status_code` so the same rendering produces the
right HTTP semantics: [`AuthenticationError`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/exceptions.py#L13-L14) (401),
[`PermissionDeniedError`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/exceptions.py#L17-L18) (403), and
[`RateLimitError`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/exceptions.py#L21-L31) (429), which also carries
`retry_after` seconds for the header. Everything else renders as 400.

## ApiErrorMiddleware

[`ApiErrorMiddleware`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/middleware.py#L18-L55) sits last in `MIDDLEWARE` (so its
`process_exception` runs first) and renders two exception types as
`{"message", "extra"}` JSON: `ApplicationError` with the subclass's status
and a `Retry-After` header when the error carries one, and Django's
`ValidationError` as a 400 whose `extra.fields` maps field names to
messages — which is how a service's `full_clean()` failure reaches a JSON
client without the endpoint doing anything.

It only applies to API views: [`_is_api_view`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/middleware.py#L12-L15) accepts a
view whose module lives under [the `api` package](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/middleware.py#L9) or that
carries the `api_view` attribute `api_auth` stamps (which is how the test
suite's throwaway endpoints, defined outside `api/`, still get JSON
errors). HTML views keep Django's normal error pages, rendered from the
templates in `template_overrides/`.

## Body parsing

The parsing helpers raise the same way, so malformed input is
indistinguishable in shape from a business failure:
[`parse_body`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/parsing.py#L9-L19) tolerates an empty body (returns `{}`) but
rejects non-JSON and non-object bodies, and
[`parse_int`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/parsing.py#L22-L27) / [`parse_float`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/parsing.py#L30-L35) read
optional numeric fields with defaults, naming the offending key in the
error. An endpoint that parses, calls a service and returns needs no error
handling of its own at any step.
