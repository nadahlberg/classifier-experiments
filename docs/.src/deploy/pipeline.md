# The deploy pipeline

A deploy is one Pulumi update: [`deploy.yml`](sym:f130adaa6aca) runs
`pulumi up` on the `prod` stack, and the Pulumi program does everything a
deploy needs — builds and pushes the image, provisions infrastructure, runs
migrations, and rolls the workloads. There is no separate build-and-push
step to drift out of sync with the infrastructure definition.

## When it runs

The workflow subscribes to the [ci workflow](ci.md)'s completion on `main`
and proceeds only when that run succeeded, so nothing unreviewed or red ever
deploys. `workflow_dispatch` allows a manual run, and a `concurrency` group
of `deploy` serializes updates — two merges in quick succession queue rather
than race the stack.

The checkout pins `github.event.workflow_run.head_sha`, the exact commit CI
tested, and passes the same sha as `IMAGE_TAG`, so the image tag in the
registry is always a commit that passed CI.

## The gate

Before Pulumi runs, a shell step fails fast if `DIGITALOCEAN_TOKEN`,
`DIGITALOCEAN_PROJECT_NAME` or `DIGITALOCEAN_REGISTRY_NAME` is missing —
Pulumi's own error for an unset registry name arrives minutes in and names
the resource, not the secret. The workflow also serializes the whole
repository secret set as `ALL_SECRETS`, which becomes the app's runtime
environment; the guard on that hand-off is [its own page](secrets.md).

## The infra project

`infra/` is a separate uv project — [its own
`pyproject.toml`](sym:d85f62513d5f) and [lockfile](sym:ce028744d03e) pin the
Pulumi providers apart from the app's dependencies, and
[`Pulumi.yaml`](sym:ff7ba30f4e94) declares the uv toolchain so
`pulumi/actions` can resolve the environment itself. State lives in Pulumi
Cloud, authenticated by `PULUMI_ACCESS_TOKEN`.

What the program actually builds is split across two pages:
[Infrastructure](infrastructure.md) for the DigitalOcean resources and
[Workloads](workloads.md) for what runs inside the cluster.
