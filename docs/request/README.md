# The request layer

How a request finds its endpoint, who may call it, and how failures come
back. Read in this order:

- [URL routing](routing.md) — the pattern lists, surface naming, and the
  third-party mounts.
- [Errors](errors.md) — `ApplicationError`, the JSON error middleware, and
  body parsing.
- [API authentication](api-auth.md) — `api_auth`, the two credential
  systems behind one header, permissions versus scopes, and the test
  URLconf the machinery is tested through.
- [Rate limiting](ratelimit.md) — the tiered budgets, how MCP traffic
  shares them, and the configuration relationships the tests pin.
- [Permissions and groups](permissions.md) — the vocabulary, where each
  layer checks it, and the post-migrate handlers that create it.
- [Cursor pagination](pagination.md) — the opaque cursor helpers.
