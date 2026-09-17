# Deploy secrets

The app's runtime secrets are GitHub repository secrets, handed to Pulumi as
one JSON blob (`ALL_SECRETS`, built with `toJSON(secrets)` in the deploy
workflow) and filtered into the `app-env` Kubernetes Secret. The filter is
where a deploy could silently destroy its own configuration, so it is
guarded.

## The filter

[`app_secrets`](sym:61c958ff8ffe+) parses the blob, drops empty values, and
strips [`INFRA_ONLY_SECRETS`](sym:68b44ec976c7) — the DigitalOcean and
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
[`update`](sym:3112745495d5) and [`preview`](sym:b91ca8039498) fixtures
toggling `is_dry_run`: [an unset variable blocks an
update](sym:1eea5bd49d3e+) but [allows a preview](sym:3922e5b9abc9+); [a
payload of only infra keys blocks](sym:123129a17705+), because
present-but-filtered-to-nothing is as destructive as absent; [malformed
JSON blocks](sym:0b7f4f39243d+) rather than degrading into an empty dict;
and [a realistic payload passes through with the infra keys and empty
values removed](sym:64d95c3a7228+).
