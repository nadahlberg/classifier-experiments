# Workloads

Everything inside the Kubernetes cluster is declared in the second half of
`infra/__main__.py`, mirroring the dev compose file service for service: the
same image runs web, worker and beat, and redis and elasticsearch run as
plain in-cluster workloads rather than managed services.

## Reaching the cluster

The program deploys into the cluster it just created:
[`cluster_credentials`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L133) looks the cluster up by name,
[`kubeconfig`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L134-L136) is marked secret (it is also
exported, which is how the reset workflow connects), and a dedicated
[Kubernetes provider](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L138) built from it is
attached to every in-cluster resource via
[`k8s_opts`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L139).
[`registry_creds`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L141-L146) (read-only) become the
[`pull_secret`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L148-L153) that every pod spec references through
[`pull_secrets`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L294), since the registry is
private.

## Redis and elasticsearch

[Redis](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L157-L175) is a one-replica Deployment with [a Service named
`redis`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L177-L182), matched by [shared
labels](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L155) — no volume, because everything it
holds (cache entries, rate-limit counters, queued tasks) is reconstructible.
[Elasticsearch](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L186-L255) is a StatefulSet with a 10Gi volume claim
and a privileged init container raising `vm.max_map_count`, which
elasticsearch requires of its host; [its Service](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L257-L262) and
[labels](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L184) follow the same pattern. The
Service names are the contract: the app-env sets `REDIS_URL` and
`ELASTICSEARCH_URL` to `redis:6379` and `elasticsearch:9200`, resolved by
cluster DNS.

## The app environment

[`app_env`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L268-L291) is one Kubernetes Secret holding the app's
entire environment: the repository secrets that survive the
[ALL_SECRETS guard](secrets.md), a
[Pulumi-generated `SECRET_KEY`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L264) (stable across deploys,
unlike the dev default which regenerates per process),
[`ALLOWED_HOSTS`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L266) (the domain plus
`localhost` — the readiness probe needs `localhost`, or `*` when no domain
is set), the postgres connection fields read off the cluster resource, the
in-cluster redis and elasticsearch URLs, and `USE_S3=on` with the bucket
names and Spaces credentials. Every container mounts it wholesale through
[`env_from`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L293). Notably `DEBUG` is simply never
set, so production runs with Django's secure-mode settings on (see
[Runtime configuration](runtime-configuration.md)).

## Migrate, then roll

[`migrate`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L296-L322) is a Job — `manage migrate`
then `collectstatic` — that `depends_on` the image and is in turn a
dependency of all three Deployments, so a deploy orders itself: build,
migrate, roll. Replicas never race migrations at boot, which is why the
image's entrypoint does not migrate. The Job's name embeds the image tag
implicitly through its spec hash, so each deploy runs a fresh Job and
`ttl_seconds_after_finished` reaps it.

[The django Deployment](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L326-L361) (labels
[`app: django`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L324)) runs the image's default
entrypoint and gets two probes: a TCP liveness check and a readiness check
that curls `/api/health/` with every backing service listed, so a pod that
cannot reach postgres, redis, elasticsearch or either bucket is pulled from
the load balancer rather than serving errors. The
[worker](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L365-L392) and [beat](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L396-L423) Deployments (their
own [label](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L363)
[pairs](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L394)) run `celery -A starter worker` and
`beat` exactly as compose does, with no probes — celery's own retry loop is
the recovery mechanism.

## The load balancer and DNS

[`django_service`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L441-L450) is a LoadBalancer Service over the
django pods. With a domain set, [its annotations](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L425)
tell DigitalOcean's cloud controller to attach the Let's Encrypt
certificate, terminate TLS on 443, and redirect HTTP to HTTPS; [the port
list](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L426) grows the 443 entry the same way.
Without a domain there is just port 80 to the pods.

The apex A record points at [`lb_ip`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/__main__.py#L452), read
straight off the Service. The AAAA record is harder: the Service never
reports its IPv6, so the program looks the load balancer up by name — and
the name is derived, not returned. [`default_lb_name`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/load_balancer.py#L1-L3)
re-implements Kubernetes' `DefaultLoadBalancerName` ("a" + Service UID,
dashes stripped, 32-character cap), and
[a unit test](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/infra/tests/test_load_balancer.py#L25-L36) pins the derivation, truncation included,
because drift here fails `pulumi up` only after merge. The record must be
Pulumi-managed at all: an unmanaged AAAA record survived a load balancer
replacement pointing at the dead IPv6 and broke IPv6 clients while IPv4
looked healthy (the 2026-08-19 incident recorded in the test's docstring).
