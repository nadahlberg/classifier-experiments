# Testing

The suite runs with pytest-django against the real settings module, and the
project's testing philosophy comes from CLAUDE.md: when code needs
explaining, write a test named after the rule instead of a comment — so the
test files are where the reasoning lives, and their docstrings run as long
as they need to. The fixtures in `starter/app/tests/conftest.py` are the
shared substrate.

## Isolation fixtures

[`local_cache`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/conftest.py#L23-L39) is autouse: every test gets a fresh
in-memory cache instead of redis. Either of its two reasons alone would
force it — CI runs no redis, and the site name reaches every rendered page
through a cached selector, so most tests would die on a connection error;
and a redis value cached by one test would outlive that test's rolled-back
transaction and be served to the next one. `starter/mcp/tests` sits outside
this conftest's reach, so it carries [its own copy](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/mcp/tests/conftest.py#L7-L22) —
needed there because the MCP middleware charges every authenticated tool
call to rate-limit buckets that live in the cache.

[`search_index`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/conftest.py#L43-L59) repoints `ELASTICSEARCH_INDEX_PREFIX` at
`test-search` and deletes those indices afterwards. Dev and the tests share
one elasticsearch, and index names have no equivalent of pytest-django's
`test_` database prefix, so without this a test's alias swap would replace
the dev index under the running site. Cleanup resolves the wildcard to
concrete names first, because elasticsearch rejects wildcard deletes
(`action.destructive_requires_name`) — which also sweeps up strays from
crashed runs.

[`memory_storage`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/conftest.py#L63-L76) redirects `DemoUpload.file` writes to
an `InMemoryStorage` by patching the bound field's `storage` attribute. A
settings override cannot do this: a FileField's callable storage is
evaluated once at model-class load, so overriding `STORAGES` later never
reaches the already-bound field, and tests would silently write real files
into `media/private`.

## Actor fixtures

Three accounts cover the permission spectrum: [`user`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/conftest.py#L80-L82)
(plain, no groups), [`other_user`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/conftest.py#L86-L88) (for proving one
caller cannot touch another's data), and [`admin_user`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/conftest.py#L92-L96)
(in the Admin group, so it holds `app.manage_admin`). All three go through
the real `user_create` service rather than `User.objects.create`, so
whatever the service enforces holds in tests too.

## Credential fixtures

Two factory pairs mirror the two API credential systems (see
[API authentication](../request/api-auth.md)): [`mint`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/conftest.py#L100-L115)
creates a personal API token through the real `api_token_create` service
(both demo scopes unless told otherwise) and
[`token_auth`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/conftest.py#L119-L125) renders its plaintext as the
`Authorization: Token ...` header; [`grant`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/conftest.py#L129-L158) fabricates
an OAuth application and access token the way the consent flow would, and
[`bearer_auth`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/conftest.py#L162-L168) renders the `Bearer` header. Tests
exercising an endpoint under both credential types compose the same
request with either pair.
