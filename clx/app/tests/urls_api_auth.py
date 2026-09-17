"""A URLconf of throwaway endpoints for exercising the auth machinery.

The machinery is product code; the demo surface is not. Testing it through
`/api/demos/auth/...` would mean the whole suite dies the day someone drops
the demo domain, which the project is deliberately arranged to allow. These
endpoints exist only for the tests, so each one can be the narrowest thing
that exercises a single rule, and the demo can be deleted without touching
them.

The token API is included as-is because it is real product surface.
"""

from django.http import HttpRequest, JsonResponse
from django.urls import include, path
from django.views.decorators.http import require_GET, require_POST

from clx.app.api.utils import PUBLIC, SESSION, TOKEN, Auth, api_auth
from clx.app.permissions import MANAGE_ADMIN, MANAGE_DEVELOPER
from clx.app.urls import tokens_api_patterns

BURST_LIMIT = 5
BURST_WINDOW_SECONDS = 60


def _echo(request: HttpRequest) -> JsonResponse:
    auth: Auth = request.auth  # type: ignore[attr-defined]
    return JsonResponse(
        {
            "user": auth.user.email,
            "auth_method": auth.method,
            "token_name": auth.token.name if auth.token else None,
            "client": auth.client,
            "scopes": list(auth.scopes),
        }
    )


async def _async_echo(request: HttpRequest) -> JsonResponse:
    return _echo(request)


@require_GET
def open_endpoint(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"auth_method": None})


@require_GET
@api_auth(PUBLIC)
def public_endpoint(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"auth_method": None})


session_only = require_GET(api_auth(SESSION)(_echo))
token_only = require_GET(api_auth(TOKEN)(_echo))
either = require_GET(api_auth(SESSION, TOKEN)(_echo))
scoped_read = require_GET(
    api_auth(SESSION, TOKEN, scopes=["demo:read"])(_echo)
)
scoped_write = require_POST(
    api_auth(SESSION, TOKEN, scopes=["demo:write"])(_echo)
)
scoped_both = require_POST(
    api_auth(SESSION, TOKEN, scopes=["demo:read", "demo:write"])(_echo)
)
admin_only = require_GET(api_auth(SESSION, TOKEN, perms=[MANAGE_ADMIN])(_echo))
developer_only = require_GET(
    api_auth(SESSION, TOKEN, perms=[MANAGE_DEVELOPER])(_echo)
)
admin_and_scope = require_GET(
    api_auth(SESSION, TOKEN, perms=[MANAGE_ADMIN], scopes=["demo:read"])(_echo)
)
burst = require_GET(
    api_auth(SESSION, TOKEN, rate=(BURST_LIMIT, BURST_WINDOW_SECONDS))(_echo)
)
async_either = require_GET(api_auth(SESSION, TOKEN)(_async_echo))

urlpatterns = [
    path("api/tokens/", include(tokens_api_patterns)),
    path("t/open/", open_endpoint, name="t-open"),
    path("t/public/", public_endpoint, name="t-public"),
    path("t/session/", session_only, name="t-session"),
    path("t/token/", token_only, name="t-token"),
    path("t/either/", either, name="t-either"),
    path("t/scoped-read/", scoped_read, name="t-scoped-read"),
    path("t/scoped-write/", scoped_write, name="t-scoped-write"),
    path("t/scoped-both/", scoped_both, name="t-scoped-both"),
    path("t/admin/", admin_only, name="t-admin"),
    path("t/developer/", developer_only, name="t-developer"),
    path("t/admin-and-scope/", admin_and_scope, name="t-admin-and-scope"),
    path("t/burst/", burst, name="t-burst"),
    path("t/async/", async_either, name="t-async"),
]
