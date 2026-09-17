# Database reset

[`reset-database.yml`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/.github/workflows/reset-database.yml) wipes the production database on
demand — a capability a starter project wants while iterating and a real
one deletes, which is why the workflow file's own comment says deleting the
file removes the capability.

It is deliberately hard to run by accident: manual dispatch only, the
literal phrase `reset production database` typed as input, the
`production` environment (so environment protection rules can require a
reviewer), and the same `deploy` concurrency group, so a reset cannot
interleave with a deploy.

The mechanics reuse what the deploy already published: `pulumi stack output`
names the cluster, `doctl` saves its kubeconfig, and the job finds the
`app-env-*` Secret in the cluster rather than receiving credentials — the
database password never appears in workflow logs or GitHub secrets beyond
what the cluster already holds. A one-shot `kubectl run` pod (postgres 17,
env from that Secret) executes `DROP SCHEMA public CASCADE; CREATE SCHEMA
public;` and re-grants, leaving an empty schema. Nothing re-migrates
automatically: the step summary says to deploy, because the migrate Job in
the next deploy is what rebuilds the schema.
