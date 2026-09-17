from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from django.core.cache import cache
from django.db import transaction

Service = TypeVar("Service", bound=Callable[..., Any])


def busts_cache(*keys: str) -> Callable[[Service], Service]:
    """Drop ``keys`` once the surrounding transaction commits."""

    def decorator(fn: Service) -> Service:
        @wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            result = fn(*args, **kwargs)
            transaction.on_commit(lambda: cache.delete_many(keys))
            return result

        wrapped.busts_cache = keys  # type: ignore[attr-defined]
        return cast(Service, wrapped)

    return decorator
