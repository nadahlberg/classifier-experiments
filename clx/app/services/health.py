import json
from collections.abc import Callable
from functools import partial
from typing import Literal
from urllib.parse import urlsplit
from urllib.request import urlopen

from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import Storage, storages
from django.db import OperationalError, connection
from django.urls import resolve

from clx.app.cache import HEALTH_PING_CACHE_KEY, HEALTH_PING_CACHE_TTL
from clx.celery import app as celery_app

ServiceName = Literal[
    "postgres",
    "redis",
    "elasticsearch",
    "celery",
    "public_storage",
    "private_storage",
]


def health_check_postgres() -> bool:
    """Check that postgres is reachable."""
    try:
        connection.ensure_connection()
        return True
    except OperationalError:
        return False


def health_check_storage(alias: str, *, served: bool = False) -> bool:
    """Check that the storage backend is writable, and serves its files if served."""
    storage = storages[alias]
    try:
        name = storage.save("health_check", ContentFile(b"ok"))
        try:
            return not served or _check_url(storage, name)
        finally:
            storage.delete(name)
    except Exception:
        return False


def _check_url(storage: Storage, name: str) -> bool:
    """Check that a saved file is reachable at its URL."""
    url = storage.url(name)
    if urlsplit(url).scheme:
        with urlopen(url, timeout=5) as response:
            return bool(response.status == 200)
    resolve(urlsplit(url).path)
    return True


def health_check_elasticsearch() -> bool:
    """Check that the elasticsearch cluster is reachable and not red."""
    try:
        url = f"{settings.ELASTICSEARCH_URL}/_cluster/health"
        with urlopen(url, timeout=5) as response:
            return json.load(response)["status"] in ("green", "yellow")
    except Exception:
        return False


def health_check_redis() -> bool:
    """Check that redis is reachable."""
    try:
        cache.set(HEALTH_PING_CACHE_KEY, "ok", timeout=HEALTH_PING_CACHE_TTL)
        return True
    except Exception:
        return False


def health_check_celery() -> bool:
    """Check that a celery worker responds to a ping."""
    try:
        return bool(celery_app.control.ping(timeout=1))
    except Exception:
        return False


CHECKS: dict[ServiceName, Callable[[], bool]] = {
    "postgres": health_check_postgres,
    "redis": health_check_redis,
    "elasticsearch": health_check_elasticsearch,
    "celery": health_check_celery,
    "public_storage": partial(health_check_storage, "default", served=True),
    "private_storage": partial(health_check_storage, "private"),
}


def health_check_services(
    names: list[ServiceName] | None = None,
) -> dict[str, bool]:
    """Check the named services, or all of them."""
    return {name: CHECKS[name]() for name in names or CHECKS}
