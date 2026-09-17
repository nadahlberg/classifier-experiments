import pytest
from django.core.cache import caches
from pytest_django.fixtures import SettingsWrapper


@pytest.fixture(autouse=True)
def local_cache(settings: SettingsWrapper) -> None:
    """Give every MCP test an empty in-memory cache.

    The app suite has the same fixture, and this directory sits outside its
    conftest's reach. It matters here because ToolMiddleware charges every
    authenticated tool call to the rate-limit buckets, which live in the
    cache: CI runs no redis, so without this every such call would be a
    connection error, and locally a counter surviving one test would
    rate-limit the next.
    """
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
    caches["default"].clear()
