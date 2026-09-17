# Infrastructure

`infra/__main__.py` declares every DigitalOcean resource the app runs on.
This page covers the platform half — managed services, buckets, DNS, the
registry and the image build; what runs inside the Kubernetes cluster is
[Workloads](workloads.md).

## Inputs

The program is parameterized entirely by environment variables and one stack
config value. [`config`](sym:c479cdb46cb2) supplies
[`region`](sym:145640fcf727,a1852e2022e7), defaulting to `nyc3`; everything
else arrives from the deploy workflow's secrets:
[`domain_name`](sym:e8ee1c13e906,dfe1b5d6619a) (optional — every
HTTPS-related resource branches on it),
[`image_tag`](sym:3ed7fe041094,04f044380c6c) (the commit sha, defaulting to
`dev` for local previews), [`do_token`](sym:018b858bd7af,6bbc8730b051)
(required — doubles as the registry push credential), and the three registry
and project names
[`PROJECT_NAME`](sym:c926c3089f79,754c2f604eaf),
[`REGISTRY_NAME`](sym:3b2a25059acf,aa91166469df) and
[`REGISTRY_TIER`](sym:7aba9497e88a,cfd5be4c47f7). Registry names are
globally unique across DigitalOcean and immutable after creation, which is
why the name is an input rather than a derived value.

## Managed services

[`postgres`](sym:82a0fb7aca38) is a managed single-node DatabaseCluster —
the one store whose durability is DigitalOcean's problem, matching the
app's rule that postgres is the source of truth. A DatabaseFirewall
restricts it to traffic from [`cluster`](sym:a176796467d5), the Kubernetes
cluster (one small node, latest available version), so the database is
unreachable from the public internet.

## Storage buckets

A dedicated [`spaces_key`](sym:e43452c25e8c) with full access feeds a
[second provider instance](sym:c074722ba9da,c93d73bfc392), because bucket
operations authenticate with Spaces keys rather than the API token. It
creates [`public_bucket`](sym:2314ee7163d2) (public-read: static files and
public media) and [`private_bucket`](sym:3fdaf45103d0) (private uploads,
served only through signed URLs) — the two buckets the app's `STORAGES`
setting expects when `USE_S3` is on.

## Domain and certificate

With `DOMAIN` set, the program creates the DNS zone and a Let's Encrypt
certificate for it, and the load balancer terminates HTTPS (see
[Workloads](workloads.md) for the DNS records, which need the load
balancer to exist first). Unset, the app is served plain HTTP at the load
balancer IP — usable for a project that has not picked a name yet.

[`project`](sym:bfe3a584196c) files every created resource
([`project_resources`](sym:0f294a377fd0,bfeb4129efa6)) under one
DigitalOcean project, so the account's dashboard groups them.

## The registry and the image

[`registry`](sym:4683dda04b64,9893637d4cef) is created with
`protect=True`: registry names cannot be re-created once taken, so an
accidental `pulumi destroy` refusing to delete it is the desired failure.
[`image`](sym:76171421abb9,cd8beef52fb9) builds
`docker/django/Dockerfile` for linux/amd64 with the repo as context and
pushes [`image_ref`](sym:a960a7debd27,6b715e7ac708) — the registry's
[endpoint](sym:30cc45fd4026,d77609496ffe) plus `starter:<sha>` — using the
API token as both username and password, which is how DigitalOcean registry
auth works. Building inside `pulumi up` is what lets the migrate job and the
deployments simply `depends_on` the image resource.

The program ends by exporting the outputs later stages and humans need —
the load balancer IP, image ref, postgres credentials, kubeconfig, bucket
names and Spaces keys — which is what `pulumi stack output` reads (the
[database reset workflow](database-reset.md) finds the cluster that way).
