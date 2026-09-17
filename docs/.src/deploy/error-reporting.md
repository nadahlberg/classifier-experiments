# Error reporting

Sentry is opt-in by environment: with [`SENTRY_DSN`](sym:1a3a88f4c83d)
unset the SDK [is never initialised](sym:158a61bb0d8b), so dev and any
deployment without the secret run with zero Sentry code active. When set,
the SDK initialises at settings-import time with logs enabled,
`send_default_pii` on, and tracing at
[`SENTRY_TRACES_SAMPLE_RATE`](sym:3ad5271c5e82,e7687a4c39a9) — hardcoded to
1.0, sampling every request, which is the right default until traffic makes
it expensive.

`send_default_pii` is what makes scrubbing necessary: it attaches request
headers, and requests carry credentials.
[`scrub_sentry_event`](sym:85d5a94fecd8+,84eb5512c506) runs as both
`before_send` and `before_send_transaction`, replaces every header named in
[`SENTRY_SCRUBBED_HEADERS`](sym:07aaf4289df1) (authorization, cookie,
x-csrftoken, idempotency-key — compared case-insensitively, since header
casing varies by client) with `[Filtered]`, and drops cookies entirely, so
an API token or session never leaves the process inside an error report
while the rest of the request context still arrives.
