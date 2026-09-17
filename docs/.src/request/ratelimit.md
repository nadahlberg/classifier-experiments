# Rate limiting

Rate limits are tiered budgets in redis, counted per user — never per
token, so minting or rotating credentials cannot reset anything. The
counters live behind django-ratelimit's `get_usage`, but the policy — which
buckets a request is charged to — is entirely this project's.

## The tiers

Every request is counted against every tier that applies, and
[`_consume`](sym:57920eace4a3+) raises
[`RateLimitError`](errors.md) the moment any bucket is exhausted;
otherwise it returns a [`RateLimitState`](sym:824a66404085+) describing the
*tightest* bucket, which is what the response headers report — the number
a client should pace against. Each tier is a
[`RateLimit`](sym:f2a2b93bfe51+) (group, identifier, limit, window) fed
through [`_usage`](sym:f3c2601da851) with `increment=True`; a tier with a
zero limit is skipped.

[`_rate_limits`](sym:b1fa63317f2d+) picks the tiers by credential kind:

- **Sessions** get one ceiling,
  [`API_RATE_LIMIT_PER_SESSION`](sym:b5ee9d4369c7) (10,000/window) — a
  person clicking, deliberately higher than the token ceiling and not
  scope-limited, because a session carries no scopes to charge.
- **Tokens** get [`API_RATE_LIMIT_PER_USER`](sym:48ec67146ab1)
  (2,000/window) as the aggregate ceiling, plus
  [one budget per scope the endpoint requires](sym:759c6e19677a+) — keyed
  `user:scope`, sized by
  [`scope_rate_limit`](sym:132869a18acc) from
  [`API_RATE_LIMIT_PER_SCOPE`](sym:177304c0f5ef) with
  [`API_RATE_LIMIT_PER_SCOPE_DEFAULT`](sym:25031e882122) for unlisted
  scopes. An endpoint requiring no scopes charges [a shared `unscoped`
  budget](sym:d9c5c2ff6308), so unscoped endpoints cannot be free.
- Either kind can add [a per-endpoint burst budget](sym:7fca0f22d99a+) via
  `api_auth`'s `rate=(limit, seconds)`.

All windows are [`API_RATE_LIMIT_WINDOW_SECONDS`](sym:c8ee515e734c) (an
hour) except a burst's own. [`rate_limit_apply`](sym:07cdc364ec0d+) is the
entry point `api_auth` calls; [`rate_limit_consume`](sym:45425ff9a37e+) is
the request-free twin the MCP `ToolMiddleware` charges tool calls
through — it fabricates an empty `HttpRequest` and spends from the *same*
buckets, which is what keeps a user's aggregate ceiling actually
aggregate across HTTP and MCP.

## Failure posture

[`API_RATE_LIMIT_FAIL_OPEN`](sym:407c0c02e69b) is wired into the package's
own [`RATELIMIT_FAIL_OPEN`](sym:2ba4ca6df657): a redis outage lets
authenticated traffic through rather than rejecting everything.
[`RATELIMIT_CACHE_PREFIX`](sym:821018c08d50) namespaces the counters in
the shared redis, and [`SILENCED_SYSTEM_CHECKS`](sym:81b3be393d4d) mutes
`django_ratelimit.W001`, which only complains that Django's own RedisCache
is not on the package's tested-backend allowlist.

## What the tests pin

[`test_api_ratelimit.py`](sym:3f59c5f2bb4a) runs against the same
[test URLconf](api-auth.md) and covers the tier relationships. Keying:
[minting a new token does not reset the user ceiling](sym:84520f283371),
[rotation does not reset a scope budget](sym:df8c3c156d1d), and
[one user's limit never affects another](sym:f55df4a6543b) — [scope
budgets included](sym:7b2d65a9027b). Tier separation: [a session is not
capped at the token ceiling](sym:a0104f5011f8) but [still has its
own](sym:f10ed34662be), and [is not scope-limited](sym:2f9576e52810);
[each scope's budget is separate](sym:b882477f59df), [an endpoint
requiring two scopes charges both](sym:631c7ca8e8a0), and [an unscoped
endpoint spends the default budget](sym:328fcc9d38d4). Aggregation:
[the user ceiling is shared across the two credential
systems](sym:c63f62bd6bb6), and [MCP tool calls drain the same scope
buckets HTTP reads](sym:54d8d8d28de0+) — if `rate_limit_consume` ever grew
its own key shapes, MCP traffic would quietly stop counting.

Three tests pin configuration relationships that nothing else would catch:
[every scope budget stays at or below the user ceiling](sym:9dcd445dfa8f+)
(a budget above the ceiling can never bind, and the demo page would print
it as if it applied), [the fail-open setting actually reaches the
package](sym:2921bf5fa8de+) (django-ratelimit has never heard of
`API_RATE_LIMIT_FAIL_OPEN`), and [the silenced W001 check is only hiding
an untested backend, not a broken one](sym:f58c7d6db49e+) — it starts
failing the day the cache moves to a backend that genuinely cannot count.
