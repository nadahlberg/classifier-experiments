from typing import cast, get_args

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from clx.app.api.utils import PUBLIC, api_auth
from clx.app.exceptions import ApplicationError
from clx.app.services.health import ServiceName, health_check_services


@require_http_methods(["GET", "HEAD"])
@api_auth(PUBLIC)
def health(request: HttpRequest) -> JsonResponse:
    """Health check endpoint."""
    param = request.GET.get("services")
    names = param.split(",") if param else None
    if names:
        unknown = set(names) - set(get_args(ServiceName))
        if unknown:
            raise ApplicationError(
                f"Unknown services: {', '.join(sorted(unknown))}"
            )
    services = health_check_services(cast("list[ServiceName] | None", names))
    healthy = all(services.values())
    return JsonResponse(
        {"status": healthy, "services": services},
        status=200 if healthy else 503,
    )
