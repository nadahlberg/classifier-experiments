import os

import pulumi
import pulumi_digitalocean as do
import pulumi_docker_build as docker_build
import pulumi_kubernetes as k8s
import pulumi_random as random
from deploy_secrets import app_secrets
from load_balancer import default_lb_name
from project import project_args
from registry import registry_args

config = pulumi.Config()
region = config.get("region") or "nyc3"
domain_name = os.getenv("DOMAIN")
image_tag = os.getenv("IMAGE_TAG", "dev")
do_token = os.environ["DIGITALOCEAN_TOKEN"]

PROJECT_NAME = os.environ["DIGITALOCEAN_PROJECT_NAME"]
REGISTRY_NAME = os.environ["DIGITALOCEAN_REGISTRY_NAME"]
REGISTRY_TIER = os.getenv("DIGITALOCEAN_REGISTRY_TIER") or "basic"

# --- Platform -------------------------------------------------------

postgres = do.DatabaseCluster(
    "clx-postgres",
    engine="pg",
    version="17",
    region=region,
    size="db-s-1vcpu-1gb",
    node_count=1,
)

cluster = do.KubernetesCluster(
    "clx-k8s",
    region=region,
    version=do.get_kubernetes_versions().latest_version,
    node_pool=do.KubernetesClusterNodePoolArgs(
        name="default",
        size="s-2vcpu-4gb",
        node_count=1,
    ),
)

do.DatabaseFirewall(
    "clx-postgres-firewall",
    cluster_id=postgres.id,
    rules=[do.DatabaseFirewallRuleArgs(type="k8s", value=cluster.id)],
)

spaces_key = do.SpacesKey(
    "clx-spaces",
    grants=[do.SpacesKeyGrantArgs(bucket="", permission="fullaccess")],
)

spaces = do.Provider(
    "spaces",
    spaces_access_id=spaces_key.access_key,
    spaces_secret_key=spaces_key.secret_key,
)

public_bucket = do.SpacesBucket(
    "clx-public",
    region=region,
    acl="public-read",
    opts=pulumi.ResourceOptions(provider=spaces),
)

private_bucket = do.SpacesBucket(
    "clx-private",
    region=region,
    acl="private",
    opts=pulumi.ResourceOptions(provider=spaces),
)

if domain_name:
    domain = do.Domain("domain", name=domain_name)
    certificate = do.Certificate(
        "clx-certificate",
        type="lets_encrypt",
        domains=[domain.name],
    )

# --- Project --------------------------------------------------------

project_inputs, project_import_id = project_args(PROJECT_NAME, do.get_project)
project = do.Project(
    "project",
    **project_inputs,
    opts=pulumi.ResourceOptions(import_=project_import_id),
)

project_resources = [
    postgres.cluster_urn,
    cluster.cluster_urn,
    public_bucket.bucket_urn,
    private_bucket.bucket_urn,
]
if domain_name:
    project_resources.append(domain.domain_urn)

do.ProjectResources(
    "project-resources",
    project=project.id,
    resources=project_resources,
)

# --- Image ----------------------------------------------------------

registry_inputs, registry_import_id = registry_args(
    REGISTRY_NAME, REGISTRY_TIER, region, do.get_container_registry
)
registry = do.ContainerRegistries(
    "registry",
    **registry_inputs,
    opts=pulumi.ResourceOptions(protect=True, import_=registry_import_id),
)

registry_endpoint = registry.endpoint
image_ref = pulumi.Output.concat(registry_endpoint, f"/clx:{image_tag}")

image = docker_build.Image(
    "image",
    tags=[image_ref],
    context={"location": ".."},
    dockerfile={"location": "../docker/django/Dockerfile"},
    platforms=[docker_build.Platform.LINUX_AMD64],
    push=True,
    registries=[
        {
            "address": "registry.digitalocean.com",
            "username": pulumi.Output.secret(do_token),
            "password": pulumi.Output.secret(do_token),
        }
    ],
    opts=pulumi.ResourceOptions(depends_on=[registry]),
)

# --- Workloads ------------------------------------------------------

cluster_credentials = do.get_kubernetes_cluster_output(name=cluster.name)
kubeconfig = pulumi.Output.secret(
    cluster_credentials.kube_configs[0].raw_config
)

kube = k8s.Provider("doks", kubeconfig=kubeconfig)
k8s_opts = pulumi.ResourceOptions(provider=kube)

registry_creds = do.ContainerRegistryDockerCredentials(
    "registry-creds",
    registry_name=REGISTRY_NAME,
    write=False,
    opts=pulumi.ResourceOptions(depends_on=[registry]),
)

pull_secret = k8s.core.v1.Secret(
    "registry-pull",
    type="kubernetes.io/dockerconfigjson",
    string_data={".dockerconfigjson": registry_creds.docker_credentials},
    opts=k8s_opts,
)

redis_labels = {"app": "redis"}

redis_deployment = k8s.apps.v1.Deployment(
    "redis",
    spec={
        "selector": {"match_labels": redis_labels},
        "template": {
            "metadata": {"labels": redis_labels},
            "spec": {
                "containers": [
                    {
                        "name": "redis",
                        "image": "redis:7",
                        "ports": [{"container_port": 6379}],
                    }
                ],
            },
        },
    },
    opts=k8s_opts,
)

redis_service = k8s.core.v1.Service(
    "redis",
    metadata={"name": "redis"},
    spec={"selector": redis_labels, "ports": [{"port": 6379}]},
    opts=k8s_opts,
)

elasticsearch_labels = {"app": "elasticsearch"}

elasticsearch_statefulset = k8s.apps.v1.StatefulSet(
    "elasticsearch",
    spec={
        "service_name": "elasticsearch",
        "selector": {"match_labels": elasticsearch_labels},
        "template": {
            "metadata": {"labels": elasticsearch_labels},
            "spec": {
                "security_context": {"fs_group": 1000},
                "init_containers": [
                    {
                        "name": "max-map-count",
                        "image": "busybox:1.37",
                        "command": [
                            "sysctl",
                            "-w",
                            "vm.max_map_count=262144",
                        ],
                        "security_context": {"privileged": True},
                    }
                ],
                "containers": [
                    {
                        "name": "elasticsearch",
                        "image": "elasticsearch:9.5.1",
                        "ports": [{"container_port": 9200}],
                        "env": [
                            {
                                "name": "discovery.type",
                                "value": "single-node",
                            },
                            {
                                "name": "xpack.security.enabled",
                                "value": "false",
                            },
                            {
                                "name": "ES_JAVA_OPTS",
                                "value": "-Xms512m -Xmx512m",
                            },
                        ],
                        "volume_mounts": [
                            {
                                "name": "data",
                                "mount_path": "/usr/share/elasticsearch/data",
                            }
                        ],
                        "readiness_probe": {
                            "http_get": {
                                "path": "/_cluster/health",
                                "port": 9200,
                            },
                            "period_seconds": 30,
                            "timeout_seconds": 5,
                        },
                    }
                ],
            },
        },
        "volume_claim_templates": [
            {
                "metadata": {"name": "data"},
                "spec": {
                    "access_modes": ["ReadWriteOnce"],
                    "resources": {"requests": {"storage": "10Gi"}},
                },
            }
        ],
    },
    opts=k8s_opts,
)

elasticsearch_service = k8s.core.v1.Service(
    "elasticsearch",
    metadata={"name": "elasticsearch"},
    spec={"selector": elasticsearch_labels, "ports": [{"port": 9200}]},
    opts=k8s_opts,
)

secret_key = random.RandomPassword("secret-key", length=64, special=False)

allowed_hosts = f"{domain_name},localhost" if domain_name else "*"

app_env = k8s.core.v1.Secret(
    "app-env",
    string_data={
        **app_secrets(),
        "SECRET_KEY": secret_key.result,
        "ALLOWED_HOSTS": allowed_hosts,
        "DOMAIN": domain_name or "",
        "POSTGRES_HOST": postgres.host,
        "POSTGRES_PORT": postgres.port.apply(str),
        "POSTGRES_DB": postgres.database,
        "POSTGRES_USER": postgres.user,
        "POSTGRES_PASSWORD": postgres.password,
        "REDIS_URL": "redis://redis:6379",
        "ELASTICSEARCH_URL": "http://elasticsearch:9200",
        "USE_S3": "on",
        "AWS_PUBLIC_BUCKET": public_bucket.name,
        "AWS_PRIVATE_BUCKET": private_bucket.name,
        "AWS_ACCESS_KEY_ID": spaces_key.access_key,
        "AWS_SECRET_ACCESS_KEY": spaces_key.secret_key,
        "AWS_S3_ENDPOINT_URL": f"https://{region}.digitaloceanspaces.com",
        "AWS_S3_REGION_NAME": region,
    },
    opts=k8s_opts,
)

env_from = [{"secret_ref": {"name": app_env.metadata.name}}]
pull_secrets = [{"name": pull_secret.metadata.name}]

migrate = k8s.batch.v1.Job(
    "migrate",
    spec={
        "backoff_limit": 2,
        "ttl_seconds_after_finished": 600,
        "template": {
            "spec": {
                "restart_policy": "Never",
                "image_pull_secrets": pull_secrets,
                "containers": [
                    {
                        "name": "migrate",
                        "image": image_ref,
                        "command": [
                            "sh",
                            "-c",
                            "manage migrate --noinput"
                            " && manage collectstatic --noinput",
                        ],
                        "env_from": env_from,
                    }
                ],
            },
        },
    },
    opts=pulumi.ResourceOptions(provider=kube, depends_on=[image]),
)

django_labels = {"app": "django"}

django_deployment = k8s.apps.v1.Deployment(
    "django",
    spec={
        "selector": {"match_labels": django_labels},
        "template": {
            "metadata": {"labels": django_labels},
            "spec": {
                "image_pull_secrets": pull_secrets,
                "containers": [
                    {
                        "name": "django",
                        "image": image_ref,
                        "ports": [{"container_port": 8000}],
                        "env_from": env_from,
                        "liveness_probe": {
                            "tcp_socket": {"port": 8000},
                            "period_seconds": 30,
                        },
                        "readiness_probe": {
                            "http_get": {
                                "path": "/api/health/?services=postgres,redis,elasticsearch,public_storage,private_storage",
                                "port": 8000,
                                "http_headers": [
                                    {"name": "Host", "value": "localhost"}
                                ],
                            },
                            "period_seconds": 30,
                            "timeout_seconds": 5,
                        },
                    }
                ],
            },
        },
    },
    opts=pulumi.ResourceOptions(provider=kube, depends_on=[migrate]),
)

celery_worker_labels = {"app": "celery-worker"}

celery_worker = k8s.apps.v1.Deployment(
    "celery-worker",
    spec={
        "selector": {"match_labels": celery_worker_labels},
        "template": {
            "metadata": {"labels": celery_worker_labels},
            "spec": {
                "image_pull_secrets": pull_secrets,
                "containers": [
                    {
                        "name": "celery-worker",
                        "image": image_ref,
                        "command": [
                            "celery",
                            "-A",
                            "clx",
                            "worker",
                            "-l",
                            "info",
                        ],
                        "env_from": env_from,
                    }
                ],
            },
        },
    },
    opts=pulumi.ResourceOptions(provider=kube, depends_on=[migrate]),
)

celery_beat_labels = {"app": "celery-beat"}

celery_beat = k8s.apps.v1.Deployment(
    "celery-beat",
    spec={
        "selector": {"match_labels": celery_beat_labels},
        "template": {
            "metadata": {"labels": celery_beat_labels},
            "spec": {
                "image_pull_secrets": pull_secrets,
                "containers": [
                    {
                        "name": "celery-beat",
                        "image": image_ref,
                        "command": [
                            "celery",
                            "-A",
                            "clx",
                            "beat",
                            "-l",
                            "info",
                        ],
                        "env_from": env_from,
                    }
                ],
            },
        },
    },
    opts=pulumi.ResourceOptions(provider=kube, depends_on=[migrate]),
)

service_annotations = {}
service_ports = [{"name": "http", "port": 80, "target_port": 8000}]
if domain_name:
    service_annotations = {
        "service.beta.kubernetes.io/do-loadbalancer-type": "REGIONAL",
        "service.beta.kubernetes.io/do-loadbalancer-protocol": "http",
        "service.beta.kubernetes.io/do-loadbalancer-certificate-id": (
            certificate.uuid
        ),
        "service.beta.kubernetes.io/do-loadbalancer-tls-ports": "443",
        "service.beta.kubernetes.io/do-loadbalancer-redirect-http-to-https": (
            "true"
        ),
    }
    service_ports.append({"name": "https", "port": 443, "target_port": 8000})

django_service = k8s.core.v1.Service(
    "web",
    metadata={"annotations": service_annotations},
    spec={
        "type": "LoadBalancer",
        "selector": django_labels,
        "ports": service_ports,
    },
    opts=k8s_opts,
)

lb_ip = django_service.status.load_balancer.ingress[0].ip

if domain_name:
    lb = do.get_load_balancer_output(
        name=django_service.metadata.uid.apply(default_lb_name)
    )
    do.DnsRecord(
        "app",
        domain=domain.name,
        type="A",
        name="@",
        value=lb_ip,
        ttl=300,
    )
    do.DnsRecord(
        "app-ipv6",
        domain=domain.name,
        type="AAAA",
        name="@",
        value=lb.ipv6,
        ttl=300,
    )
    pulumi.export("app_url", f"https://{domain_name}")
    pulumi.export("domain", domain_name)
    pulumi.export("certificate_id", certificate.uuid)
    pulumi.export("load_balancer_ipv6", lb.ipv6)

# --- Outputs --------------------------------------------------------

pulumi.export("load_balancer_ip", lb_ip)
pulumi.export("image", image_ref)
pulumi.export("registry_endpoint", registry_endpoint)
pulumi.export("postgres_host", postgres.host)
pulumi.export("postgres_port", postgres.port)
pulumi.export("postgres_user", postgres.user)
pulumi.export("postgres_password", postgres.password)
pulumi.export("postgres_database", postgres.database)
pulumi.export("cluster_name", cluster.name)
pulumi.export("kubeconfig", kubeconfig)
pulumi.export("public_bucket", public_bucket.name)
pulumi.export("private_bucket", private_bucket.name)
pulumi.export("spaces_endpoint", f"https://{region}.digitaloceanspaces.com")
pulumi.export("spaces_access_key", spaces_key.access_key)
pulumi.export("spaces_secret_key", spaces_key.secret_key)
