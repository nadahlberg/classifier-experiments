import pytest
from django.core.cache import cache
from django.test import Client
from pytest_django.fixtures import (
    DjangoAssertNumQueries,
    DjangoCaptureOnCommitCallbacks,
)

from clx.app.cache import SITE_CONFIG_CACHE_KEY
from clx.app.selectors.site_config import site_config_get
from clx.app.services.site_config import site_config_update
from clx.app.services.utils import busts_cache


@pytest.mark.django_db
def test_a_warm_config_cache_costs_no_query(
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """The point of the lazy cache: the first read fills it, later reads
    never reach the database.

    The site name is on the config, and the context processor puts it on
    every rendered page, so a selector that re-queried would add a query to
    every request in the app. This fails if site_config_get stops writing what
    it read back into the cache.
    """
    site_config_get()

    with django_assert_num_queries(0):
        assert site_config_get().site_name == "Classifier Experiments"


@pytest.mark.django_db
def test_the_cached_config_is_dropped_only_once_the_write_commits(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """busts_cache defers the delete to on_commit, not to the end of the
    decorated call.

    Deleting eagerly would let a concurrent reader re-cache the old row
    from its own snapshot before the write lands, and a rolled-back write
    would evict a value that never changed. Capturing the callbacks is what
    makes the two halves visible: inside the block the key is still there,
    and running them clears it. This fails if the delete moves out of
    on_commit.
    """
    site_config_get()

    with django_capture_on_commit_callbacks(execute=True):
        site_config_update(site_name="Acme")
        assert cache.get(SITE_CONFIG_CACHE_KEY) is not None

    assert cache.get(SITE_CONFIG_CACHE_KEY) is None
    assert site_config_get().site_name == "Acme"


@pytest.mark.django_db
def test_a_page_title_follows_the_configured_site_name(
    client: Client,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """The site name is a config field, not a setting.

    Renaming the product is a row update at runtime, so the whole chain has
    to hold: the service writes, the bust drops the cached copy, and the
    context processor re-reads. This fails if any template goes back to
    reading a settings value.
    """
    with django_capture_on_commit_callbacks(execute=True):
        site_config_update(site_name="Acme")

    response = client.get("/", secure=True)

    assert "<title>Acme</title>" in response.content.decode()


def test_busts_cache_exposes_its_keys() -> None:
    """busts_cache stashes the keys it will drop on the wrapper it returns,
    so tooling can learn which cache keys a service busts by reading that
    attribute instead of parsing the decorator's source. This fails if the
    stash is dropped or renamed.
    """

    @busts_cache("alpha", "beta")
    def touch() -> None:
        return None

    assert touch.busts_cache == ("alpha", "beta")  # type: ignore[attr-defined]
