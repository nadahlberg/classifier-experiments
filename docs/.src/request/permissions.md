# Permissions and groups

Authorization vocabulary is defined once, in `permissions.py`, and created
in the database by `post_migrate` handlers — so a fresh database, dev or
production, has the same groups the moment migrations finish.

## The vocabulary

[`PERMISSIONS`](sym:972d970816f5) defines two custom permissions and
[`GROUPS`](sym:ad46fc90e4f2) maps them onto two groups: `Admin` holds
`manage_admin`; `Developer` holds both `manage_admin` and
`manage_developer`, so a developer is a superset of an admin. Endpoints
and tools name them through the dotted constants
[`MANAGE_ADMIN`](sym:e9f8e1ae31a5) and
[`MANAGE_DEVELOPER`](sym:52a14dd1d858) rather than hand-typed strings —
a typo in a permission string fails closed and silently locks everyone
out, where a typo in a constant name is an `ImportError`. Codenames use
underscores because the template `perms` lookup cannot resolve a hyphen.

[`API_SCOPES`](sym:213d01719056) is the one scope vocabulary for every
token system: personal API tokens validate against it,
[the OAuth provider registers it as its `SCOPES`](sym:3b70764b789f) (so
the consent screen offers exactly these names), and the MCP resource
metadata advertises it. Permissions bind the user; scopes narrow one
credential — the split is enforced in
[API authentication](api-auth.md).

## Where each layer checks

Each layer guards with the mechanism that belongs to it: templates use the
built-in `perms` context variable to hide links; HTML views wear
`@permission_required` (rule E702); API endpoints declare `perms=` on
`api_auth` (E701); MCP tools set `required_perms` (enforced by
`ToolMiddleware`). Hiding a control and guarding its destination are
always both done — the template check is never a substitute.

## Created on migrate

[`AppConfig.ready`](sym:1fb924646cf7+) imports the checks package (which
registers the pattern checks) and connects three `post_migrate` handlers —
the only place signal connections are allowed (rule E603).
[`sync_permissions_and_groups`](sym:e929cfffe9be) get-or-creates every
permission against the `User` content type and *sets* each group's
permission list, so removing a codename from `GROUPS` revokes it on the
next migrate rather than leaving it behind.
[`create_site_config`](sym:c5e4f700b770) guarantees the singleton
`SiteConfig` row exists (see [Caching](../mechanisms/caching.md)).
[`create_dev_user`](sym:1f2efb93c37b+) seeds a standing login when
[`DEV_USER_EMAIL`](sym:e9cb65001a9f) and
[`DEV_USER_PASSWORD`](sym:79b9c0d8af48) are both set: created through the
real `user_create` service, email pre-verified, and in the `Developer`
group. It never touches an existing account, and leaving the variables
unset anywhere you don't want a standing login is the off switch — the
compose file sets them, production only if the repository secrets do.
