import uuid
from typing import cast

from django.http import HttpRequest, JsonResponse
from django.utils.formats import date_format
from django.utils.timezone import localtime
from django.views.decorators.http import require_GET, require_POST

from clx.app.api.utils import SESSION, api_auth, parse_body, parse_int
from clx.app.exceptions import ApplicationError
from clx.app.models import User
from clx.app.permissions import MANAGE_ADMIN
from clx.app.selectors.user import USER_LEVELS, user_level, user_search
from clx.app.services.site_config import site_config_update
from clx.app.services.user import user_level_set


@require_POST
@api_auth(SESSION, perms=[MANAGE_ADMIN])
def settings_update(request: HttpRequest) -> JsonResponse:
    """Update the site config from the admin settings page."""
    body = parse_body(request)
    site_config = site_config_update(site_name=str(body.get("site_name", "")))
    return JsonResponse({"site_name": site_config.site_name})


@require_GET
@api_auth(SESSION, perms=[MANAGE_ADMIN])
def user_list(request: HttpRequest) -> JsonResponse:
    """Search one page of users for the admin users page."""
    actor = cast("User", request.user)
    actor_rank = USER_LEVELS.index(user_level(actor))
    result = user_search(
        query=str(request.GET.get("search", "")),
        level=str(request.GET.get("level", "")),
        page=parse_int(request.GET, "page", default=1),
    )
    return JsonResponse(
        {
            "users": [
                {
                    "id": str(user.id),
                    "email": user.email,
                    "name": f"{user.first_name} {user.last_name}".strip(),
                    "initial": user.email[0],
                    "joined": date_format(
                        localtime(user.date_joined), "M j, Y"
                    ),
                    "last_login": (
                        date_format(localtime(user.last_login), "M j, Y")
                        if user.last_login
                        else ""
                    ),
                    "level": user_level(user),
                    "self": user == actor,
                    "editable": user != actor
                    and USER_LEVELS.index(user_level(user)) <= actor_rank,
                }
                for user in result["users"]
            ],
            "page": result["page"],
            "pages": result["pages"],
            "total": result["total"],
            "max_level": user_level(actor),
        }
    )


@require_POST
@api_auth(SESSION, perms=[MANAGE_ADMIN])
def user_level_update(request: HttpRequest) -> JsonResponse:
    """Set a user's permission level from the admin users page."""
    body = parse_body(request)
    try:
        user_id = uuid.UUID(str(body.get("user_id", "")))
    except ValueError as error:
        raise ApplicationError("user_id must be a UUID") from error
    user = User.objects.filter(id=user_id).first()
    if user is None:
        raise ApplicationError("User not found")
    user = user_level_set(
        actor=cast("User", request.user),
        user=user,
        level=str(body.get("level", "")),
    )
    return JsonResponse({"id": str(user.id), "level": user_level(user)})
