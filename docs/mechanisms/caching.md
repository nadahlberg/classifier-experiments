# Caching

The cache is redis through Django's cache API — [the same instance celery
brokers through](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L182-L187) — and the whole pattern is a pairing:
a key read by a cached selector must be named by every service that writes
what it holds, because nothing else expires it inside the TTL.

## Keys live in one file

Every cache key is a constant in `app/cache.py` (rule E601 rejects literal
keys at call sites): [`SITE_CONFIG_CACHE_KEY` with its TTL beside
it](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/cache.py#L1), [`DEMO_HEARTBEAT_CACHE_KEY`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/cache.py#L4)
(no TTL — the heartbeat value is timestamped, not expired),
and [the health ping key and its one-second TTL](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/cache.py#L6).
Dynamic keys are *builders* in the same file, not f-strings at call sites:
[`demo_chat_cancel_cache_key`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/cache.py#L12-L14) (per-thread cancel flag,
with [its TTL](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/cache.py#L9)) and
[`demo_chat_events_channel`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/cache.py#L17-L19) — which names a redis
pub/sub channel rather than a cache key, but lives here because it is the
same kind of shared name.

## Reads cache lazily, in the selector

[`site_config_get`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/selectors/site_config.py#L7-L15) is the model to copy: return the
cached value if it is there, otherwise fetch the singleton row, set with
the key's TTL, and return. [The `site_config` context
processor](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/context_processors.py#L7-L9) puts the row on every template context, which
is exactly why the cache exists — [a warm cache costs zero
queries](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_site_config.py#L16-L30), so the site name on every page does not add a
query to every request.

## Writes bust, in the service

[`busts_cache`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/services/utils.py#L11-L24) runs the service, then
drops the named keys with `transaction.on_commit` — the same discipline as
queueing a task, and for the same reason: a rolled-back write must not
evict a value that never changed, and an eager delete would let a
concurrent reader re-cache the old row from its own snapshot before the
write lands. [The test makes both halves
visible](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_site_config.py#L34-L54) by capturing the on-commit callbacks: inside
the transaction the key is still warm, after commit it is gone. The
decorator also stashes its keys as a `busts_cache` attribute on the
wrapper, [pinned by its own test](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_site_config.py#L77-L88) because the codebase
explorer reads that attribute to link service cards to the keys they bust.

[`site_config_update`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/services/site_config.py#L7-L13) is the worked example: strip,
`full_clean`, save, and the decorator handles invalidation. The end-to-end
chain — write, bust, re-read, render — is pinned by [a test that renames
the site and asserts the page title follows](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_site_config.py#L58-L74): the site
name is a config row, not a setting, so renaming the product is a runtime
update. The row itself is guaranteed by the `post_migrate` handler (see
[Permissions and groups](../request/permissions.md)).
