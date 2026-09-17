# Error reporting

Sentry is opt-in by environment: with [`SENTRY_DSN`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L284)
unset the SDK [is never initialised](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L310), so dev and any
deployment without the secret run with zero Sentry code active. When set,
the SDK initialises at settings-import time with logs enabled,
`send_default_pii` on, and tracing at
[`SENTRY_TRACES_SAMPLE_RATE`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L285) — hardcoded to
1.0, sampling every request, which is the right default until traffic makes
it expensive.

`send_default_pii` is what makes scrubbing necessary: it attaches request
headers, and requests carry credentials.
[`scrub_sentry_event`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L295-L305) runs as both
`before_send` and `before_send_transaction`, replaces every header named in
[`SENTRY_SCRUBBED_HEADERS`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L287-L292) (authorization, cookie,
x-csrftoken, idempotency-key — compared case-insensitively, since header
casing varies by client) with `[Filtered]`, and drops cookies entirely, so
an API token or session never leaves the process inside an error report
while the rest of the request context still arrives.
