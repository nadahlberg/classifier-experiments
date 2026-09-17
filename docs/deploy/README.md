# Deploy

How a merged commit becomes the running site, and what it runs on. Read in
this order:

- [CI](ci.md) — the five checks every push and PR runs; a green run on
  `main` is the deploy trigger.
- [The deploy pipeline](pipeline.md) — `deploy.yml` and the Pulumi project;
  one `pulumi up` builds, migrates and rolls.
- [Infrastructure](infrastructure.md) — the DigitalOcean resources: managed
  postgres, the cluster, buckets, domain, registry, and the image build.
- [Workloads](workloads.md) — everything inside Kubernetes: redis,
  elasticsearch, the app environment, the migrate-then-roll ordering, the
  load balancer and DNS.
- [Deploy secrets](secrets.md) — the `ALL_SECRETS` hand-off and the guard
  that keeps a local `pulumi up` from emptying the app's environment.
- [Runtime configuration](runtime-configuration.md) — how settings read the
  environment, and what flips when `DEBUG` is off.
- [Error reporting](error-reporting.md) — Sentry, and the header scrubbing
  that keeps credentials out of events.
- [Database reset](database-reset.md) — the deliberately awkward workflow
  that wipes production.
