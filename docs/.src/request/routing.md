# URL routing

All routing lives in one `urls.py`, organised as named pattern lists that
[`urlpatterns`](sym:318c9360eeed,45b23743fc46,00249e4c65dd,eaa4f5884b40,33139197aac3,915b7ef2bd51,16e04c2b9045,e845cf05595e,b61915f62962,798b5b91f852,84d63f54daec,5420b5bfd190)
assembles at the bottom: one list per view domain, one per API surface, and
the shared prefix is applied where a list is included — never repeated
inside it. The naming discipline (list name, include prefix, interface
module and URL-name prefixes all derived from one surface name) is enforced
by the E301–E304 checks in [The rule catalog](../conventions/rules.md).

## View lists

[`main_view_patterns`](sym:7ca09526bef0,e34a5d49ba36,2428378c67ce) holds
the general pages — the index and the profile — and is spread into
`urlpatterns` directly because its routes share no prefix.
[`demos_view_patterns`](sym:d03b75470a38,628b3a132026,0144b0d52869,e7d52bcc8dfa,1a964ac3beac,c9d4dfc74ce5,44450141c3c3,4f1506c29fae,010c52bae5de,4d0cdff4a752,f17183115783,5c8b3916bde3,2f8c25d7fe9e)
routes one thin view per demo page under `demos/`, and
[`admin_view_patterns`](sym:a2071bab40fd,7545b3f53635,2000e3302b8f,cee5eabf3d19)
routes the three admin pages under `admin/` with a bare route that
redirects to `admin-settings` — which is why `pages/admin/` legitimately
has no `index.html` (rule E406 accepts a redirecting bare route).

[`pwa_patterns`](sym:f0c064d75655,186606a24654,f8910ec0f055) is kept apart
from the app's own pages: it serves `pages/sw.js` and
`pages/manifest.webmanifest` as `TemplateView`s with explicit content
types. The service worker must be routed at the root, because a service
worker only controls paths at or below its own URL.

## API lists

Each API surface gets `<surface>_api_patterns`, included under
`api/<surface>/`:
[`health_api_patterns`](sym:dd8fefe59083,5bf454cc11ce) (one route),
[`users_api_patterns`](sym:549860932149,a5440b2f22e1,b0ee8a5e71a3),
[`admin_api_patterns`](sym:4699de7b0caf,918d877d8a45,ea82bd1f987e,dd695db75c90),
[`tokens_api_patterns`](sym:5df7ebc8f28a,d31fa38a1eca,6d19b99727dc,b5ec59fd2610,2c8541205beb),
and the big one,
[`demos_api_patterns`](sym:db97a64e2f76,5268aaecc2d6,a9f7e8b0f49c,7b1c3676fc29,e17cd508a146,9172c8bd7ba3,128aaf5f2a54,59b19807532b,46f0640e0f74,ef3093215067,534584963ca6,27fdad7e4c4c,5eae0ddc5227,acb5555d821e,33f89d1c341f,b9dcc7cb9d7d,c23a05de418b,b8d94f4e78b8,87789fbff9ee,1b0c2fde3325,1314630fdb3d,22d55535672f,641934b4ce43,dcb879a02ecd,9c0a822cbacc,f8756105b35e,ada6473920a6,75ef2d6502e7,3d3860c86668,3a0b7ebb8025,3148aa46e920),
which maps every demo endpoint — jobs, dockets, uploads, the
auth-demonstration endpoints, and the chat thread routes. Every entry
points at exactly one endpoint function in the surface's `api/` module,
one route per operation, with object ids as typed path converters
(`<uuid:job_id>`) so a malformed id 404s before the endpoint runs.

## Third-party routes

Allauth is included wholesale under `accounts/`. The OAuth provider is
split deliberately:
[`oauth_metadata_patterns`](sym:6ea27a953063) (the RFC 8414 discovery
document) mounts at the root, because clients look for
`/.well-known/oauth-authorization-server` at a fixed path, while
[`oauth_patterns`](sym:9a15322daab8) — the authorize/token/revoke
endpoints plus dynamic client registration — mounts under `o/` with the
`oauth2_provider` namespace the package's reversing expects.

The tail of `urlpatterns` serves public media and static files, which is a
dev-only affordance: both helpers return nothing when `DEBUG` is off, where
S3 serves those URLs instead (see
[Storage](../mechanisms/storage.md)).
