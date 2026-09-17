import base64
import binascii
import json
from typing import Any

from clx.app.exceptions import ApplicationError


def encode_cursor(payload: dict[str, Any]) -> str:
    """Encode a cursor payload as an opaque url-safe token."""
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(token: str) -> dict[str, Any]:
    """Decode a cursor token, rejecting anything encode_cursor did not mint."""
    padded = token + "=" * (-len(token) % 4)
    try:
        parsed = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ApplicationError("Invalid cursor") from error
    if not isinstance(parsed, dict):
        raise ApplicationError("Invalid cursor")
    return parsed
