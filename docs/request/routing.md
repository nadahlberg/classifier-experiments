# URL routing

All routing lives in one `urls.py`, organised as named pattern lists that
[`urlpatterns`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/urls.py#L212-L230)
assembles at the bottom: one list per view domain, one per API surface, and
the shared prefix is applied where a list is included — never repeated
inside it. The naming discipline (list name, include prefix, interface
module and URL-name prefixes all derived from one surface name) is enforced
by the E301–E304 checks in [The rule catalog](../conventions/rules.md).

## View lists

[`main_view_patterns`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/urls.py#L13-L16) holds
the general pages — the index and the profile — and is spread into
`urlpatterns` directly because its routes share no prefix.
[`demos_view_patterns`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/urls.py#L18-L31)
routes one thin view per demo page under `demos/`, and
[`admin_view_patterns`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/urls.py#L33-L42)
routes the three admin pages under `admin/` with a bare route that
redirects to `admin-settings` — which is why `pages/admin/` legitimately
has no `index.html` (rule E406 accepts a redirecting bare route).

[`pwa_patterns`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/urls.py#L44-L61) is kept apart
from the app's own pages: it serves `pages/sw.js` and
`pages/manifest.webmanifest` as `TemplateView`s with explicit content
types. The service worker must be routed at the root, because a service
worker only controls paths at or below its own URL.

## API lists

Each API surface gets `<surface>_api_patterns`, included under
`api/<surface>/`:
[`health_api_patterns`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/urls.py#L81-L83) (one route),
[`users_api_patterns`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/urls.py#L85-L88),
[`admin_api_patterns`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/urls.py#L67-L79),
[`tokens_api_patterns`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/urls.py#L197-L210),
and the big one,
[`demos_api_patterns`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/urls.py#L90-L195),
which maps every demo endpoint — jobs, dockets, uploads, the
auth-demonstration endpoints, and the chat thread routes. Every entry
points at exactly one endpoint function in the surface's `api/` module,
one route per operation, with object ids as typed path converters
(`<uuid:job_id>`) so a malformed id 404s before the endpoint runs.

## Third-party routes

Allauth is included wholesale under `accounts/`. The OAuth provider is
split deliberately:
[`oauth_metadata_patterns`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/urls.py#L63) (the RFC 8414 discovery
document) mounts at the root, because clients look for
`/.well-known/oauth-authorization-server` at a fixed path, while
[`oauth_patterns`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/urls.py#L65) — the authorize/token/revoke
endpoints plus dynamic client registration — mounts under `o/` with the
`oauth2_provider` namespace the package's reversing expects.

The tail of `urlpatterns` serves public media and static files, which is a
dev-only affordance: both helpers return nothing when `DEBUG` is off, where
S3 serves those URLs instead (see
[Storage](../mechanisms/storage.md)).
