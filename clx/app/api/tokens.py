import uuid
from typing import Any, cast

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from clx.app.api.utils import SESSION, api_auth, parse_body, parse_int
from clx.app.models import ApiToken, User
from clx.app.permissions import API_SCOPES
from clx.app.selectors.api_token import api_token_list
from clx.app.services.api_token import (
    DEFAULT_LIFETIME_DAYS,
    MintedToken,
    api_token_create,
    api_token_revoke,
    api_token_rotate,
)


def _serialize(token: ApiToken) -> dict[str, Any]:
    return {
        "id": str(token.id),
        "name": token.name,
        "scopes": token.scopes,
        "created_at": token.created_at.isoformat(),
        "expires_at": token.expires_at.isoformat(),
        "last_used_at": (
            token.last_used_at.isoformat() if token.last_used_at else None
        ),
        "is_active": token.is_active,
        "is_revoked": token.is_revoked,
        "is_expired": token.is_expired,
    }


def _minted(minted: MintedToken) -> JsonResponse:
    return JsonResponse(
        {"token": _serialize(minted.token), "plaintext": minted.plaintext}
    )


@require_GET
@api_auth(SESSION)
def token_list(request: HttpRequest) -> JsonResponse:
    """List the caller's API tokens."""
    tokens = api_token_list(user=cast("User", request.user))
    return JsonResponse(
        {
            "tokens": [_serialize(token) for token in tokens],
            "scopes": [
                {"name": name, "description": description}
                for name, description in API_SCOPES.items()
            ],
        }
    )


@require_POST
@api_auth(SESSION)
def token_create(request: HttpRequest) -> JsonResponse:
    """Mint a token and return the plaintext, which is never stored."""
    body = parse_body(request)
    minted = api_token_create(
        user=cast("User", request.user),
        name=str(body.get("name", "")),
        scopes=list(body.get("scopes", [])),
        lifetime_days=parse_int(
            body, "lifetime_days", default=DEFAULT_LIFETIME_DAYS
        ),
    )
    return _minted(minted)


@require_POST
@api_auth(SESSION)
def token_revoke(request: HttpRequest, token_id: uuid.UUID) -> JsonResponse:
    """Revoke a token without deleting it."""
    token = api_token_revoke(
        user=cast("User", request.user), token_id=str(token_id)
    )
    return JsonResponse({"token": _serialize(token)})


@require_POST
@api_auth(SESSION)
def token_rotate(request: HttpRequest, token_id: uuid.UUID) -> JsonResponse:
    """Revoke a token and mint a replacement carrying the same scopes."""
    minted = api_token_rotate(
        user=cast("User", request.user), token_id=str(token_id)
    )
    return _minted(minted)
