import json
import os

import pulumi

INFRA_ONLY_SECRETS = {
    "DIGITALOCEAN_TOKEN",
    "DIGITALOCEAN_PROJECT_NAME",
    "DIGITALOCEAN_REGISTRY_NAME",
    "DIGITALOCEAN_REGISTRY_TIER",
    "PULUMI_ACCESS_TOKEN",
    "GITHUB_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_URL",
    "ACTIONS_RUNTIME_TOKEN",
}


def app_secrets() -> dict[str, str]:
    """Collect app secrets, refusing to empty app-env on a real update."""
    raw = os.getenv("ALL_SECRETS") or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        pulumi.log.warn("ALL_SECRETS was not valid JSON")
        parsed = {}

    secrets = {
        key: str(value)
        for key, value in parsed.items()
        if key not in INFRA_ONLY_SECRETS and value not in (None, "")
    }

    if not secrets and not pulumi.runtime.is_dry_run():
        raise ValueError(
            "ALL_SECRETS produced no app secrets, which would empty "
            "app-env. CI passes it from the repository secrets; set it "
            "in the environment to run this update."
        )

    return secrets
