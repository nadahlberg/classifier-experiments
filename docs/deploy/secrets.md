# Deploy secrets

The app's runtime secrets are GitHub repository secrets, handed to Pulumi as
one JSON blob (`ALL_SECRETS`, built with `toJSON(secrets)` in the deploy
workflow) and filtered into the `app-env` Kubernetes Secret. The filter is
where a deploy could silently destroy its own configuration, so it is
guarded.

## The filter

[`app_secrets`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/deploy_secrets.py#L19-L41) parses the blob, drops empty values, and
strips [`INFRA_ONLY_SECRETS`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/deploy_secrets.py#L6-L16) — the DigitalOcean and
Pulumi credentials plus the tokens GitHub injects into every workflow, which
power the deploy but have no business inside the app's containers.
Everything else passes through untouched, which is what makes adding a new
app secret a one-step change: set it in the repository and it appears in
`app-env` on the next deploy. The README's Environment table documents what
each supported secret does.

## The guard

Only CI ever sets `ALL_SECRETS`. A local `pulumi up` therefore sees it
empty — and without a guard that is not an error: the function would return
`{}`, Pulumi would diff `app-env` down to nothing, and the "successful"
update would strip the running app of its database credentials and signing
key. So an empty filtered result raises during a real update, while
previews are exempt because they mutate nothing and a local
`pulumi preview` is the normal way to inspect a plan.

`infra/tests/test_secrets.py` pins each edge of that behaviour with the
[`update`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/tests/test_secrets.py#L26-L28) and [`preview`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/tests/test_secrets.py#L32-L34) fixtures
toggling `is_dry_run`: [an unset variable blocks an
update](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/tests/test_secrets.py#L37-L46) but [allows a preview](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/tests/test_secrets.py#L49-L57); [a
payload of only infra keys blocks](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/tests/test_secrets.py#L60-L72), because
present-but-filtered-to-nothing is as destructive as absent; [malformed
JSON blocks](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/tests/test_secrets.py#L75-L84) rather than degrading into an empty dict;
and [a realistic payload passes through with the infra keys and empty
values removed](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/tests/test_secrets.py#L87-L111).
