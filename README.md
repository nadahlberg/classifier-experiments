# Classifier Experiments

Start the stack:

```sh
docker compose up
```

Install the tooling and activate the environment:

```sh
uv sync --extra dev
source .venv/bin/activate
```

Run a Django management command:

```sh
manage migrate
```

Run tests:

```sh
pytest
```

Run pre-commit:

```sh
pre-commit run --all-files
```

Run mypy:

```sh
mypy clx
```


## Environment

Set these as repository secrets, under Settings → Secrets and variables → Actions.

| Secret | Used for |
| --- | --- |
| `PULUMI_ACCESS_TOKEN` | Pulumi Cloud state backend |
| `DIGITALOCEAN_TOKEN` | Provisioning DigitalOcean resources and pushing to the container registry |
| `DIGITALOCEAN_PROJECT_NAME` | Name of the DigitalOcean project every resource is filed under |
| `DIGITALOCEAN_REGISTRY_NAME` | Name of the container registry. Registry names are globally unique across DigitalOcean and cannot be changed after creation |
| `DIGITALOCEAN_REGISTRY_TIER` | Subscription tier the registry is created at. Defaults to `basic`; see DigitalOcean's registry plans for the tier names — they differ in storage and how many repositories they allow, and the cheapest holds only a single repository |
| `DOMAIN` | Apex domain. Set it to get a DNS zone, a Let's Encrypt certificate and an HTTPS listener; leave it unset and the app is served over HTTP at the load balancer IP |
| `POSTMARK_SERVER_TOKEN` | Postmark server API token. Set it to send mail through Postmark; leave it unset and mail is printed to the console instead |
| `DEFAULT_FROM_EMAIL` | Address transactional mail is sent from. Postmark rejects anything that isn't a verified Sender Signature or on a verified domain |
| `SENTRY_DSN` | Sentry project DSN. Set it to report errors to Sentry; leave it unset and the SDK is never initialised |
| `DEV_USER_EMAIL` | Set together with `DEV_USER_PASSWORD` to seed an account on migrate. The account is created with its email pre-verified and added to the `Developer` group, so leave both unset anywhere you don't want a standing login |
| `DEV_USER_PASSWORD` | Password for the seeded account |
| `AUTODEPLOY` | The one repository **variable** (Variables tab, beside the secrets). Set it to `on` (or `true`/`1`/`yes`) to deploy automatically on every merge to main; leave it unset and the deploy workflow runs only when dispatched by hand from the Actions tab — manual runs ignore the gate |

The deploy fails before Pulumi runs if either DigitalOcean name is missing.
