# Runtime configuration

Settings read the environment directly with `os.getenv` — there is no
`.env` machinery — and every default is chosen so that an empty environment
yields a working dev process while production must set things explicitly.

[`getenv_list`](sym:5257fbbcf496,b26422557cd8) parses the comma-separated
variables (`ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`), dropping empties so a
trailing comma or unset variable yields `[]` rather than `[""]`. The
distinction matters more than it looks: `"".split(",")` is `[""]`, Django
matches no host against the empty string, and `DEBUG` on ignores
`ALLOWED_HOSTS` entirely — so the mistake would survive until deploy and
then 400 every request. `test_settings.py`
[re-executes settings.py under a controlled environment](sym:1c3536bebe28)
and pins [the empty case](sym:3cd8740fb98a+) and [the
values-with-a-trailing-comma case](sym:480629e90604+) for both variables.

## The mode switch

[`DEBUG`](sym:08027853b4d7) is on only when the environment literally says
`DEBUG=on` — production never sets it, and [everything security-sensitive
keys off it](sym:211fe0c80c8c): with `DEBUG` off, the process turns on the
SSL redirect (trusting `X-Forwarded-Proto` from the load balancer, since
TLS terminates there), a year of HSTS with subdomains and preload, and
secure-only session and CSRF cookies. The same flag picks the template
loader configuration (cached only in production — see
[Cotton and template loading](../templates/components.md)).

## Identity and hosts

[`SECRET_KEY`](sym:a94cbdcbeb0d) defaults to a random value per process,
which is correct for dev (no shared state worth forging) and would be a bug
in production (sessions invalidated on every restart, and every replica
disagreeing) — which is why the deploy generates one stable key per stack
(see [Workloads](workloads.md)). [`ALLOWED_HOSTS`](sym:620f9fb51070) is
empty by default, so a misdeployed process rejects traffic rather than
serving any Host header. [`DOMAIN`](sym:a71991212c14,787a67c48501) is the
apex domain when one exists; its one settings-level consumer is
[`CSRF_TRUSTED_ORIGINS`](sym:1bad3e1334e3), which must name the HTTPS origin
explicitly because CSRF origin-checking does not consult `ALLOWED_HOSTS`.
[`CORS_ALLOWED_ORIGINS`](sym:1d7260b26401) stays empty unless a separate
frontend origin needs the API, so the API is same-origin by default.

## Fixed choices

[`BASE_DIR`](sym:0ac2da26858b,fbe5be69219a) anchors every filesystem path
(templates, media) at `starter/`, not the repo root — the package is the
unit that gets installed into the image. The internationalization block
([`LANGUAGE_CODE`](sym:347f6156f46e), [`TIME_ZONE`](sym:f70cd144ca97),
[`USE_I18N`](sym:ba0b561ffaf5), [`USE_TZ`](sym:f698c1eb6346)) fixes the app
to en-us and timezone-aware UTC datetimes, and
[`DEFAULT_AUTO_FIELD`](sym:12e70476c63c) makes every implicit primary key a
`BigAutoField`, so no model ever migrates when it outgrows 32 bits.
