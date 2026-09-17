from clx.app.cache import SITE_CONFIG_CACHE_KEY
from clx.app.models import SITE_CONFIG_ID, SiteConfig
from clx.app.services.utils import busts_cache


@busts_cache(SITE_CONFIG_CACHE_KEY)
def site_config_update(*, site_name: str) -> SiteConfig:
    """Update the site config."""
    site_config = SiteConfig.objects.get(id=SITE_CONFIG_ID)
    site_config.site_name = site_name.strip()
    site_config.full_clean()
    site_config.save(update_fields=["site_name"])
    return site_config
