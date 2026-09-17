# Permissions and groups

Authorization vocabulary is defined once, in `permissions.py`, and created
in the database by `post_migrate` handlers — so a fresh database, dev or
production, has the same groups the moment migrations finish.

## The vocabulary

[`PERMISSIONS`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/permissions.py#L6-L9) defines two custom permissions and
[`GROUPS`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/permissions.py#L11-L14) maps them onto two groups: `Admin` holds
`manage_admin`; `Developer` holds both `manage_admin` and
`manage_developer`, so a developer is a superset of an admin. Endpoints
and tools name them through the dotted constants
[`MANAGE_ADMIN`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/permissions.py#L3) and
[`MANAGE_DEVELOPER`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/permissions.py#L4) rather than hand-typed strings —
a typo in a permission string fails closed and silently locks everyone
out, where a typo in a constant name is an `ImportError`. Codenames use
underscores because the template `perms` lookup cannot resolve a hyphen.

[`API_SCOPES`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/permissions.py#L16-L20) is the one scope vocabulary for every
token system: personal API tokens validate against it,
[the OAuth provider registers it as its `SCOPES`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L145) (so
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

[`AppConfig.ready`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/apps.py#L5-L18) imports the checks package (which
registers the pattern checks) and connects three `post_migrate` handlers —
the only place signal connections are allowed (rule E603).
[`sync_permissions_and_groups`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/signals.py#L17-L34) get-or-creates every
permission against the `User` content type and *sets* each group's
permission list, so removing a codename from `GROUPS` revokes it on the
next migrate rather than leaving it behind.
[`create_site_config`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/signals.py#L13-L14) guarantees the singleton
`SiteConfig` row exists (see [Caching](../mechanisms/caching.md)).
[`create_dev_user`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/signals.py#L37-L54) seeds a standing login when
[`DEV_USER_EMAIL`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L150) and
[`DEV_USER_PASSWORD`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L151) are both set: created through the
real `user_create` service, email pre-verified, and in the `Developer`
group. It never touches an existing account, and leaving the variables
unset anywhere you don't want a standing login is the off switch — the
compose file sets them, production only if the repository secrets do.
