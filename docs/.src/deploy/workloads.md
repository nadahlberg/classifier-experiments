# Workloads

Everything inside the Kubernetes cluster is declared in the second half of
`infra/__main__.py`, mirroring the dev compose file service for service: the
same image runs web, worker and beat, and redis and elasticsearch run as
plain in-cluster workloads rather than managed services.

## Reaching the cluster

The program deploys into the cluster it just created:
[`cluster_credentials`](sym:faa78fdc81ba) looks the cluster up by name,
[`kubeconfig`](sym:c3a538d73b21,45b807ad01ab) is marked secret (it is also
exported, which is how the reset workflow connects), and a dedicated
[Kubernetes provider](sym:d2f5e465a0c1,3dead87a78c7) built from it is
attached to every in-cluster resource via
[`k8s_opts`](sym:c02ebd7c2191,0d159fdb2356).
[`registry_creds`](sym:918c561a4cd5) (read-only) become the
[`pull_secret`](sym:45c86fef6386) that every pod spec references through
[`pull_secrets`](sym:167bb2c1de78,8fb1b501597d), since the registry is
private.

## Redis and elasticsearch

[Redis](sym:6f716c6589cf) is a one-replica Deployment with [a Service named
`redis`](sym:c3e93c05e174), matched by [shared
labels](sym:cf161368e5f6,ac029e52dcec) — no volume, because everything it
holds (cache entries, rate-limit counters, queued tasks) is reconstructible.
[Elasticsearch](sym:83d0a8743f13) is a StatefulSet with a 10Gi volume claim
and a privileged init container raising `vm.max_map_count`, which
elasticsearch requires of its host; [its Service](sym:321e163156b2) and
[labels](sym:72b2a37a69da,06447610d57a) follow the same pattern. The
Service names are the contract: the app-env sets `REDIS_URL` and
`ELASTICSEARCH_URL` to `redis:6379` and `elasticsearch:9200`, resolved by
cluster DNS.

## The app environment

[`app_env`](sym:3d5177a0c4da) is one Kubernetes Secret holding the app's
entire environment: the repository secrets that survive the
[ALL_SECRETS guard](secrets.md), a
[Pulumi-generated `SECRET_KEY`](sym:206f27890a41) (stable across deploys,
unlike the dev default which regenerates per process),
[`ALLOWED_HOSTS`](sym:5ab592eaa5fa,fda256bf9a15) (the domain plus
`localhost` — the readiness probe needs `localhost`, or `*` when no domain
is set), the postgres connection fields read off the cluster resource, the
in-cluster redis and elasticsearch URLs, and `USE_S3=on` with the bucket
names and Spaces credentials. Every container mounts it wholesale through
[`env_from`](sym:778aa8b15315,3d735ed77542). Notably `DEBUG` is simply never
set, so production runs with Django's secure-mode settings on (see
[Runtime configuration](runtime-configuration.md)).

## Migrate, then roll

[`migrate`](sym:5682cae15b6e,f470c1b3d049) is a Job — `manage migrate`
then `collectstatic` — that `depends_on` the image and is in turn a
dependency of all three Deployments, so a deploy orders itself: build,
migrate, roll. Replicas never race migrations at boot, which is why the
image's entrypoint does not migrate. The Job's name embeds the image tag
implicitly through its spec hash, so each deploy runs a fresh Job and
`ttl_seconds_after_finished` reaps it.

[The django Deployment](sym:67e9642239cd) (labels
[`app: django`](sym:044a4023c416,e87489a7ed9c)) runs the image's default
entrypoint and gets two probes: a TCP liveness check and a readiness check
that curls `/api/health/` with every backing service listed, so a pod that
cannot reach postgres, redis, elasticsearch or either bucket is pulled from
the load balancer rather than serving errors. The
[worker](sym:227f1e7e2730) and [beat](sym:327e68db89a3) Deployments (their
own [label](sym:4312216b641c,2a16a31f9a38)
[pairs](sym:dd7652a52f04,fe6df8ae41ee)) run `celery -A starter worker` and
`beat` exactly as compose does, with no probes — celery's own retry loop is
the recovery mechanism.

## The load balancer and DNS

[`django_service`](sym:d2b9e3841632) is a LoadBalancer Service over the
django pods. With a domain set, [its annotations](sym:ca72d0b4bcb9,405bd947c99a)
tell DigitalOcean's cloud controller to attach the Let's Encrypt
certificate, terminate TLS on 443, and redirect HTTP to HTTPS; [the port
list](sym:18affca520e2,126b3dd40160) grows the 443 entry the same way.
Without a domain there is just port 80 to the pods.

The apex A record points at [`lb_ip`](sym:0aae16185f94,7c17fb28429d), read
straight off the Service. The AAAA record is harder: the Service never
reports its IPv6, so the program looks the load balancer up by name — and
the name is derived, not returned. [`default_lb_name`](sym:85c31ed5b21c)
re-implements Kubernetes' `DefaultLoadBalancerName` ("a" + Service UID,
dashes stripped, 32-character cap), and
[a unit test](sym:b3f09aaa1e85+) pins the derivation, truncation included,
because drift here fails `pulumi up` only after merge. The record must be
Pulumi-managed at all: an unmanaged AAAA record survived a load balancer
replacement pointing at the dead IPv6 and broke IPv6 clients while IPv4
looked healthy (the 2026-08-19 incident recorded in the test's docstring).
