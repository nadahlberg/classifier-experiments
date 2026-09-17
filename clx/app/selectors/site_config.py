from django.core.cache import cache

from clx.app.cache import SITE_CONFIG_CACHE_KEY, SITE_CONFIG_CACHE_TTL
from clx.app.models import SITE_CONFIG_ID, SiteConfig


def site_config_get() -> SiteConfig:
    """The site config, from the cache when it is warm."""
    site_config = cache.get(SITE_CONFIG_CACHE_KEY)
    if not isinstance(site_config, SiteConfig):
        site_config = SiteConfig.objects.get(id=SITE_CONFIG_ID)
        cache.set(
            SITE_CONFIG_CACHE_KEY, site_config, timeout=SITE_CONFIG_CACHE_TTL
        )
    return site_config
