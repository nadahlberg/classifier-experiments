from typing import cast

from django.contrib.auth import logout
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from clx.app.api.utils import SESSION, api_auth, parse_body
from clx.app.models import User
from clx.app.services.user import user_delete, user_update


@require_POST
@api_auth(SESSION)
def me_update(request: HttpRequest) -> JsonResponse:
    """Update the caller's profile fields."""
    body = parse_body(request)
    user = user_update(
        user=cast("User", request.user),
        first_name=str(body.get("first_name", "")),
        last_name=str(body.get("last_name", "")),
    )
    return JsonResponse(
        {
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
    )


@require_POST
@api_auth(SESSION)
def me_delete(request: HttpRequest) -> JsonResponse:
    """Delete the caller's account and everything it owns."""
    user_delete(cast("User", request.user))
    logout(request)
    return JsonResponse({"deleted": True})
