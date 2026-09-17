import json
from typing import Any

from django.http import HttpRequest

from clx.app.exceptions import ApplicationError


def parse_body(request: HttpRequest) -> dict[str, Any]:
    """Parse a JSON object request body, tolerating an empty body."""
    if not request.body:
        return {}
    try:
        parsed = json.loads(request.body)
    except json.JSONDecodeError as error:
        raise ApplicationError("Request body must be JSON") from error
    if not isinstance(parsed, dict):
        raise ApplicationError("Request body must be a JSON object")
    return parsed


def parse_int(body: dict[str, Any], key: str, *, default: int) -> int:
    """Read an integer from a parsed body, defaulting when absent."""
    try:
        return int(body.get(key, default))
    except (TypeError, ValueError) as error:
        raise ApplicationError(f"{key} must be an integer") from error


def parse_float(body: dict[str, Any], key: str, *, default: float) -> float:
    """Read a float from a parsed body, defaulting when absent."""
    try:
        return float(body.get(key, default))
    except (TypeError, ValueError) as error:
        raise ApplicationError(f"{key} must be a number") from error
