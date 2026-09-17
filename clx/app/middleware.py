from collections.abc import Callable

from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse

from clx.app import api
from clx.app.exceptions import ApplicationError

API_MODULE = api.__name__


def _is_api_view(view: Callable[..., HttpResponse]) -> bool:
    return getattr(view, "api_view", False) or view.__module__.startswith(
        API_MODULE
    )


class ApiErrorMiddleware:
    def __init__(
        self, get_response: Callable[[HttpRequest], HttpResponse]
    ) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_exception(
        self, request: HttpRequest, exception: Exception
    ) -> JsonResponse | None:
        match = request.resolver_match
        if not match or not _is_api_view(match.func):
            return None

        if isinstance(exception, ApplicationError):
            response = JsonResponse(
                {"message": exception.message, "extra": exception.extra},
                status=getattr(exception, "status_code", 400),
            )
            retry_after = getattr(exception, "retry_after", 0)
            if retry_after:
                response["Retry-After"] = str(retry_after)
            return response

        if isinstance(exception, ValidationError):
            fields = (
                exception.message_dict
                if hasattr(exception, "error_dict")
                else {"non_field_errors": exception.messages}
            )
            return JsonResponse(
                {"message": "Validation error", "extra": {"fields": fields}},
                status=400,
            )

        return None
