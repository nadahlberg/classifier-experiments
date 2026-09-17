from collections.abc import Callable
from typing import Any

ProjectArgs = tuple[dict[str, str | bool | None], str | None]


def project_args(name: str, get_project: Callable[..., Any]) -> ProjectArgs:
    """Build Project inputs, adopting the account's existing project by name."""
    try:
        existing = get_project(name=name)
    except Exception:
        return {"name": name}, None
    return {
        "name": name,
        "description": existing.description or None,
        "purpose": existing.purpose or None,
        "environment": existing.environment or None,
        "is_default": existing.is_default,
    }, existing.id
