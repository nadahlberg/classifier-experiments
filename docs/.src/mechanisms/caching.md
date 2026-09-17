# Caching

The cache is redis through Django's cache API — [the same instance celery
brokers through](sym:bd77cc9c1d0b) — and the whole pattern is a pairing:
a key read by a cached selector must be named by every service that writes
what it holds, because nothing else expires it inside the TTL.

## Keys live in one file

Every cache key is a constant in `app/cache.py` (rule E601 rejects literal
keys at call sites): [`SITE_CONFIG_CACHE_KEY` with its TTL beside
it](sym:8d5f3dfffb66,7659e6967c52), [`DEMO_HEARTBEAT_CACHE_KEY`](sym:a0a54d64d6f9)
(no TTL — the heartbeat value is timestamped, not expired),
and [the health ping key and its one-second TTL](sym:5b39962f8227,c0ce9bd4e250).
Dynamic keys are *builders* in the same file, not f-strings at call sites:
[`demo_chat_cancel_cache_key`](sym:a3af71823f02) (per-thread cancel flag,
with [its TTL](sym:6483348e030b)) and
[`demo_chat_events_channel`](sym:c4a9ab9fa0a3) — which names a redis
pub/sub channel rather than a cache key, but lives here because it is the
same kind of shared name.

## Reads cache lazily, in the selector

[`site_config_get`](sym:32dbd1296cc2+) is the model to copy: return the
cached value if it is there, otherwise fetch the singleton row, set with
the key's TTL, and return. [The `site_config` context
processor](sym:d9974334f310+) puts the row on every template context, which
is exactly why the cache exists — [a warm cache costs zero
queries](sym:c5a581a5540e+), so the site name on every page does not add a
query to every request.

## Writes bust, in the service

[`busts_cache`](sym:344c7fae0d3c+,e8e81e8b5802) runs the service, then
drops the named keys with `transaction.on_commit` — the same discipline as
queueing a task, and for the same reason: a rolled-back write must not
evict a value that never changed, and an eager delete would let a
concurrent reader re-cache the old row from its own snapshot before the
write lands. [The test makes both halves
visible](sym:8a650380cf10+) by capturing the on-commit callbacks: inside
the transaction the key is still warm, after commit it is gone. The
decorator also stashes its keys as a `busts_cache` attribute on the
wrapper, [pinned by its own test](sym:24d8f543b82c+) because the codebase
explorer reads that attribute to link service cards to the keys they bust.

[`site_config_update`](sym:57db8a841db8) is the worked example: strip,
`full_clean`, save, and the decorator handles invalidation. The end-to-end
chain — write, bust, re-read, render — is pinned by [a test that renames
the site and asserts the page title follows](sym:29859fc87a38+): the site
name is a config row, not a setting, so renaming the product is a runtime
update. The row itself is guaranteed by the `post_migrate` handler (see
[Permissions and groups](../request/permissions.md)).
