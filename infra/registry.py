from collections.abc import Callable
from typing import Any

RegistryArgs = tuple[dict[str, str | None], str | None]


def registry_args(
    name: str, tier: str, region: str, get_registry: Callable[..., Any]
) -> RegistryArgs:
    """Build registry inputs, adopting the account's existing registry by name."""
    try:
        existing = get_registry(name=name)
    except Exception:
        return {
            "name": name,
            "subscription_tier_slug": tier,
            "region": region,
        }, None
    return {
        "name": name,
        "subscription_tier_slug": tier,
        "region": existing.region or None,
    }, existing.id
