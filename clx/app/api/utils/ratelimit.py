from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from django.conf import settings
from django.http import HttpRequest
from django_ratelimit.core import get_usage

from clx.app.exceptions import RateLimitError
from clx.app.permissions import scope_rate_limit


@dataclass(frozen=True)
class RateLimit:
    group: str
    identifier: str
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitState:
    limit: int
    remaining: int
    retry_after: int


def _usage(request: HttpRequest, limit: RateLimit) -> dict[str, Any] | None:
    usage = get_usage(
        request,
        group=limit.group,
        key=lambda group, req, value=limit.identifier: value,
        rate=f"{limit.limit}/{limit.window_seconds}s",
        increment=True,
    )
    return cast("dict[str, Any] | None", usage)


def _consume(request: HttpRequest, *limits: RateLimit) -> RateLimitState:
    """Count a request against every limit, raising once any is exhausted."""
    counted = [
        (limit, usage)
        for limit in limits
        if limit.limit > 0
        for usage in [_usage(request, limit)]
        if usage is not None
    ]

    for limit, usage in counted:
        if usage["should_limit"]:
            raise RateLimitError(
                "Rate limit exceeded",
                extra={"scope": limit.group, "limit": limit.limit},
                retry_after=max(0, int(usage["time_left"])),
            )

    if not counted:
        return RateLimitState(limit=0, remaining=0, retry_after=0)

    limit, usage = min(
        counted, key=lambda pair: pair[1]["limit"] - pair[1]["count"]
    )
    return RateLimitState(
        limit=int(usage["limit"]),
        remaining=max(0, int(usage["limit"]) - int(usage["count"])),
        retry_after=max(0, int(usage["time_left"])),
    )


SCOPE_RATE_LIMIT_DEFAULT_KEY = "unscoped"


def _endpoint_limit(user_id: str, rate: tuple[int, int]) -> RateLimit:
    limit, seconds = rate
    return RateLimit(
        group="api:endpoint",
        identifier=user_id,
        limit=limit,
        window_seconds=seconds,
    )


def _token_limits(
    user_id: str, scopes: tuple[str, ...], rate: tuple[int, int] | None
) -> list[RateLimit]:
    window = settings.API_RATE_LIMIT_WINDOW_SECONDS
    limits = [
        RateLimit(
            group="api:user",
            identifier=user_id,
            limit=settings.API_RATE_LIMIT_PER_USER,
            window_seconds=window,
        )
    ]
    for scope in scopes or (SCOPE_RATE_LIMIT_DEFAULT_KEY,):
        limits.append(
            RateLimit(
                group="api:scope",
                identifier=f"{user_id}:{scope}",
                limit=scope_rate_limit(scope),
                window_seconds=window,
            )
        )
    if rate is not None:
        limits.append(_endpoint_limit(user_id, rate))
    return limits


def _rate_limits(
    auth: Any, rate: tuple[int, int] | None, scopes: tuple[str, ...]
) -> list[RateLimit]:
    user_id = str(auth.user.pk)
    if auth.is_token:
        return _token_limits(user_id, scopes, rate)

    limits = [
        RateLimit(
            group="api:session",
            identifier=user_id,
            limit=settings.API_RATE_LIMIT_PER_SESSION,
            window_seconds=settings.API_RATE_LIMIT_WINDOW_SECONDS,
        )
    ]
    if rate is not None:
        limits.append(_endpoint_limit(user_id, rate))
    return limits


def rate_limit_apply(
    request: HttpRequest,
    *,
    auth: Any,
    rate: tuple[int, int] | None,
    scopes: tuple[str, ...],
) -> RateLimitState:
    """Count a request against every limit that applies to it."""
    return _consume(request, *_rate_limits(auth, rate, scopes))


def rate_limit_consume(
    *,
    user_id: int | str | UUID,
    scopes: tuple[str, ...],
    rate: tuple[int, int] | None = None,
) -> RateLimitState:
    """Count one token-authenticated call from outside the request cycle."""
    return _consume(HttpRequest(), *_token_limits(str(user_id), scopes, rate))
