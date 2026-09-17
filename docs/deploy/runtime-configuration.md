# Runtime configuration

Settings read the environment directly with `os.getenv` — there is no
`.env` machinery — and every default is chosen so that an empty environment
yields a working dev process while production must set things explicitly.

[`getenv_list`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L14-L16) parses the comma-separated
variables (`ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`), dropping empties so a
trailing comma or unset variable yields `[]` rather than `[""]`. The
distinction matters more than it looks: `"".split(",")` is `[""]`, Django
matches no host against the empty string, and `DEBUG` on ignores
`ALLOWED_HOSTS` entirely — so the mistake would survive until deploy and
then 400 every request. `test_settings.py`
[re-executes settings.py under a controlled environment](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_settings.py#L9-L20)
and pins [the empty case](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_settings.py#L24-L36) and [the
values-with-a-trailing-comma case](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_settings.py#L40-L52) for both variables.

## The mode switch

[`DEBUG`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L20) is on only when the environment literally says
`DEBUG=on` — production never sets it, and [everything security-sensitive
keys off it](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L320): with `DEBUG` off, the process turns on the
SSL redirect (trusting `X-Forwarded-Proto` from the load balancer, since
TLS terminates there), a year of HSTS with subdomains and preload, and
secure-only session and CSRF cookies. The same flag picks the template
loader configuration (cached only in production — see
[Cotton and template loading](../templates/components.md)).

## Identity and hosts

[`SECRET_KEY`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L19) defaults to a random value per process,
which is correct for dev (no shared state worth forging) and would be a bug
in production (sessions invalidated on every restart, and every replica
disagreeing) — which is why the deploy generates one stable key per stack
(see [Workloads](workloads.md)). [`ALLOWED_HOSTS`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L21) is
empty by default, so a misdeployed process rejects traffic rather than
serving any Host header. [`DOMAIN`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L22) is the
apex domain when one exists; its one settings-level consumer is
[`CSRF_TRUSTED_ORIGINS`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L55), which must name the HTTPS origin
explicitly because CSRF origin-checking does not consult `ALLOWED_HOSTS`.
[`CORS_ALLOWED_ORIGINS`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L54) stays empty unless a separate
frontend origin needs the API, so the API is same-origin by default.

## Fixed choices

[`BASE_DIR`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L11) anchors every filesystem path
(templates, media) at `starter/`, not the repo root — the package is the
unit that gets installed into the image. The internationalization block
([`LANGUAGE_CODE`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L198), [`TIME_ZONE`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L199),
[`USE_I18N`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L200), [`USE_TZ`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L201)) fixes the app
to en-us and timezone-aware UTC datetimes, and
[`DEFAULT_AUTO_FIELD`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L318) makes every implicit primary key a
`BigAutoField`, so no model ever migrates when it outgrows 32 bits.
