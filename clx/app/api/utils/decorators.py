from collections.abc import Callable, Sequence
from functools import wraps
from inspect import iscoroutinefunction
from typing import Any, TypeVar, cast

from asgiref.sync import sync_to_async
from csp.constants import SELF
from csp.decorators import csp_replace
from django.http import HttpRequest, HttpResponseBase
from django.views.decorators.csrf import csrf_exempt

from clx.app.api.utils.authentication import (
    PUBLIC,
    SESSION,
    check_perms,
    check_scopes,
    resolve_auth,
)
from clx.app.api.utils.ratelimit import RateLimitState, rate_limit_apply

View = TypeVar("View", bound=Callable[..., Any])


def frame_self(view: View) -> View:
    """Relax frame-ancestors to 'self' so our own pages can frame the response."""
    apply = csp_replace({"frame-ancestors": [SELF]})
    return cast(View, apply(cast(Any, view)))


def api_auth(
    *methods: str,
    perms: Sequence[str] = (),
    scopes: Sequence[str] = (),
    rate: tuple[int, int] | None = None,
) -> Callable[[View], View]:
    """Allow the given authentication methods, disjunctively.

    The view is exempted from Django's CSRF middleware because a token
    request carries no cookie and must not be asked for a CSRF token; the
    session authenticator re-enforces CSRF on its own path instead.
    """
    allowed = methods or (SESSION,)
    required_perms = tuple(perms)
    required_scopes = tuple(scopes)
    if PUBLIC in allowed and (
        len(allowed) > 1 or perms or scopes or rate is not None
    ):
        raise ValueError("PUBLIC declares no auth; it composes with nothing")

    def authorize(request: HttpRequest) -> RateLimitState:
        auth = resolve_auth(request, allowed)
        check_perms(auth, required_perms)
        check_scopes(auth, required_scopes)
        state = rate_limit_apply(
            request, auth=auth, rate=rate, scopes=required_scopes
        )
        request.auth = auth  # type: ignore[attr-defined]
        request.user = auth.user
        return state

    def stamp(response: HttpResponseBase, state: RateLimitState) -> None:
        if state.limit:
            response["X-RateLimit-Limit"] = str(state.limit)
            response["X-RateLimit-Remaining"] = str(state.remaining)

    config = {
        "methods": allowed,
        "perms": required_perms,
        "scopes": required_scopes,
        "rate": rate,
    }

    def decorator(view: View) -> View:
        if iscoroutinefunction(view):

            @wraps(view)
            async def async_wrapper(
                request: HttpRequest, *args: Any, **kwargs: Any
            ) -> HttpResponseBase:
                if PUBLIC in allowed:
                    return cast(
                        HttpResponseBase, await view(request, *args, **kwargs)
                    )
                state = await sync_to_async(authorize)(request)
                response = cast(
                    HttpResponseBase, await view(request, *args, **kwargs)
                )
                stamp(response, state)
                return response

            async_wrapper.api_view = True  # type: ignore[attr-defined]
            async_wrapper.api_auth = config  # type: ignore[attr-defined]
            return cast(View, csrf_exempt(async_wrapper))

        @wraps(view)
        def wrapper(
            request: HttpRequest, *args: Any, **kwargs: Any
        ) -> HttpResponseBase:
            if PUBLIC in allowed:
                return cast(HttpResponseBase, view(request, *args, **kwargs))
            state = authorize(request)
            response = cast(HttpResponseBase, view(request, *args, **kwargs))
            stamp(response, state)
            return response

        wrapper.api_view = True  # type: ignore[attr-defined]
        wrapper.api_auth = config  # type: ignore[attr-defined]
        return cast(View, csrf_exempt(wrapper))

    return decorator
