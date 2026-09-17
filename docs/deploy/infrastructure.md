# Infrastructure

`infra/__main__.py` declares every DigitalOcean resource the app runs on.
This page covers the platform half — managed services, buckets, DNS, the
registry and the image build; what runs inside the Kubernetes cluster is
[Workloads](workloads.md).

## Inputs

The program is parameterized entirely by environment variables and one stack
config value. [`config`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L11) supplies
[`region`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L12), defaulting to `nyc3`; everything
else arrives from the deploy workflow's secrets:
[`domain_name`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L13) (optional — every
HTTPS-related resource branches on it),
[`image_tag`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L14) (the commit sha, defaulting to
`dev` for local previews), [`do_token`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L15)
(required — doubles as the registry push credential), and the three registry
and project names
[`PROJECT_NAME`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L17),
[`REGISTRY_NAME`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L18) and
[`REGISTRY_TIER`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L19). Registry names are
globally unique across DigitalOcean and immutable after creation, which is
why the name is an input rather than a derived value.

## Managed services

[`postgres`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L23-L30) is a managed single-node DatabaseCluster —
the one store whose durability is DigitalOcean's problem, matching the
app's rule that postgres is the source of truth. A DatabaseFirewall
restricts it to traffic from [`cluster`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L32-L41), the Kubernetes
cluster (one small node, latest available version), so the database is
unreachable from the public internet.

## Storage buckets

A dedicated [`spaces_key`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L49-L52) with full access feeds a
[second provider instance](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L54-L58), because bucket
operations authenticate with Spaces keys rather than the API token. It
creates [`public_bucket`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L60-L65) (public-read: static files and
public media) and [`private_bucket`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L67-L72) (private uploads,
served only through signed URLs) — the two buckets the app's `STORAGES`
setting expects when `USE_S3` is on.

## Domain and certificate

With `DOMAIN` set, the program creates the DNS zone and a Let's Encrypt
certificate for it, and the load balancer terminates HTTPS (see
[Workloads](workloads.md) for the DNS records, which need the load
balancer to exist first). Unset, the app is served plain HTTP at the load
balancer IP — usable for a project that has not picked a name yet.

[`project`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L84) files every created resource
([`project_resources`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L86-L91)) under one
DigitalOcean project, so the account's dashboard groups them.

## The registry and the image

[`registry`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L103-L109) is created with
`protect=True`: registry names cannot be re-created once taken, so an
accidental `pulumi destroy` refusing to delete it is the desired failure.
[`image`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L114-L129) builds
`docker/django/Dockerfile` for linux/amd64 with the repo as context and
pushes [`image_ref`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L112) — the registry's
[endpoint](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L111) plus `starter:<sha>` — using the
API token as both username and password, which is how DigitalOcean registry
auth works. Building inside `pulumi up` is what lets the migrate job and the
deployments simply `depends_on` the image resource.

The program ends by exporting the outputs later stages and humans need —
the load balancer IP, image ref, postgres credentials, kubeconfig, bucket
names and Spaces keys — which is what `pulumi stack output` reads (the
[database reset workflow](database-reset.md) finds the cluster that way).
