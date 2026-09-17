# Template placement

Every template is exactly one of four things, decided by asking in order
and stopping at the first yes: dictated by a package →
`template_overrides/`; rendered by a URL → `templates/pages/`; a frame
several pages share → `templates/layouts/`; otherwise →
`templates/cotton/`. The E401–E407 checks in
[The rule catalog](../conventions/rules.md) enforce the consequences —
dead pages, dead layouts, unused components, same-name file/folder pairs.

## The two roots

[`TEMPLATES`](sym:7e8313970717) lists both directories, `templates` first,
with resolution by name — so a template in one root can extend or include
one in the other. `template_overrides/` holds templates a package asks for
by name: their paths are a contract, like a URL, which is why they sit
outside the placement rule rather than as an exception to it. The test is
whether something else requests the path — `account/login.html` qualifies
(allauth renders it), `404.html` qualifies (Django's error views name it),
but `cotton/account/fields.html` does not: allauth never requests that
path, so it is an ordinary component that happens to serve those pages.
The directory doubles as the list of files to re-check when a package is
upgraded.

## Cotton without the cached-loader trap

Cotton is registered in [`INSTALLED_APPS`](sym:342b95adb811) as
`django_cotton.apps.SimpleAppConfig`, not `django_cotton`: the default
AppConfig rewrites the `loaders` entry and force-wraps everything in
Django's cached loader regardless of `DEBUG`, which silently stops
template edits from taking effect until the process restarts — under
uvicorn nothing clears that cache the way `runserver`'s reloader does. So
[the loader list](sym:f30f289d7528,13b2a0e209cf) is configured by hand:
cotton's loader first, then the filesystem and app-directories loaders,
wrapped in the cached loader only when `DEBUG` is off. The `builtins`
entry registers cotton's tags and the project's `{% script %}` tag on
every template, so no template ever `{% load %}`s them.

Context processors add `request`, `auth`, `messages` and the
[site config](../mechanisms/caching.md) to every render.
`COTTON_ENABLE_CONTEXT_ISOLATION` stays off deliberately: nested
components inheriting the page context is what makes extracting a chunk
of a page for legibility a rename rather than an interface design task.
