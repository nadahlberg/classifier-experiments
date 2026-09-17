# Rate limiting

Rate limits are tiered budgets in redis, counted per user — never per
token, so minting or rotating credentials cannot reset anything. The
counters live behind django-ratelimit's `get_usage`, but the policy — which
buckets a request is charged to — is entirely this project's.

## The tiers

Every request is counted against every tier that applies, and
[`_consume`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/ratelimit.py#L39-L67) raises
[`RateLimitError`](errors.md) the moment any bucket is exhausted;
otherwise it returns a [`RateLimitState`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/ratelimit.py#L22-L25) describing the
*tightest* bucket, which is what the response headers report — the number
a client should pace against. Each tier is a
[`RateLimit`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/ratelimit.py#L14-L18) (group, identifier, limit, window) fed
through [`_usage`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/ratelimit.py#L28-L36) with `increment=True`; a tier with a
zero limit is skipped.

[`_rate_limits`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/ratelimit.py#L109-L126) picks the tiers by credential kind:

- **Sessions** get one ceiling,
  [`API_RATE_LIMIT_PER_SESSION`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L266) (10,000/window) — a
  person clicking, deliberately higher than the token ceiling and not
  scope-limited, because a session carries no scopes to charge.
- **Tokens** get [`API_RATE_LIMIT_PER_USER`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L265)
  (2,000/window) as the aggregate ceiling, plus
  [one budget per scope the endpoint requires](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/ratelimit.py#L83-L106) — keyed
  `user:scope`, sized by
  [`scope_rate_limit`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/permissions.py#L23-L29) from
  [`API_RATE_LIMIT_PER_SCOPE`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L268-L272) with
  [`API_RATE_LIMIT_PER_SCOPE_DEFAULT`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L267) for unlisted
  scopes. An endpoint requiring no scopes charges [a shared `unscoped`
  budget](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/ratelimit.py#L70), so unscoped endpoints cannot be free.
- Either kind can add [a per-endpoint burst budget](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/ratelimit.py#L73-L80) via
  `api_auth`'s `rate=(limit, seconds)`.

All windows are [`API_RATE_LIMIT_WINDOW_SECONDS`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L273) (an
hour) except a burst's own. [`rate_limit_apply`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/ratelimit.py#L129-L137) is the
entry point `api_auth` calls; [`rate_limit_consume`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/api/utils/ratelimit.py#L140-L147) is
the request-free twin the MCP `ToolMiddleware` charges tool calls
through — it fabricates an empty `HttpRequest` and spends from the *same*
buckets, which is what keeps a user's aggregate ceiling actually
aggregate across HTTP and MCP.

## Failure posture

[`API_RATE_LIMIT_FAIL_OPEN`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L274) is wired into the package's
own [`RATELIMIT_FAIL_OPEN`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L276): a redis outage lets
authenticated traffic through rather than rejecting everything.
[`RATELIMIT_CACHE_PREFIX`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L277) namespaces the counters in
the shared redis, and [`SILENCED_SYSTEM_CHECKS`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L278) mutes
`django_ratelimit.W001`, which only complains that Django's own RedisCache
is not on the package's tested-backend allowlist.

## What the tests pin

[`test_api_ratelimit.py`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L18-L21) runs against the same
[test URLconf](api-auth.md) and covers the tier relationships. Keying:
[minting a new token does not reset the user ceiling](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L24-L52),
[rotation does not reset a scope budget](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L193-L210), and
[one user's limit never affects another](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L55-L76) — [scope
budgets included](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L164-L190). Tier separation: [a session is not
capped at the token ceiling](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L79-L106) but [still has its
own](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L109-L121), and [is not scope-limited](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L337-L356);
[each scope's budget is separate](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L124-L161), [an endpoint
requiring two scopes charges both](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L213-L248), and [an unscoped
endpoint spends the default budget](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L251-L275). Aggregation:
[the user ceiling is shared across the two credential
systems](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L278-L303), and [MCP tool calls drain the same scope
buckets HTTP reads](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L306-L334) — if `rate_limit_consume` ever grew
its own key shapes, MCP traffic would quietly stop counting.

Three tests pin configuration relationships that nothing else would catch:
[every scope budget stays at or below the user ceiling](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L359-L383)
(a budget above the ceiling can never bind, and the demo page would print
it as if it applied), [the fail-open setting actually reaches the
package](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L386-L403) (django-ratelimit has never heard of
`API_RATE_LIMIT_FAIL_OPEN`), and [the silenced W001 check is only hiding
an untested backend, not a broken one](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_api_ratelimit.py#L406-L433) — it starts
failing the day the cache moves to a backend that genuinely cannot count.
