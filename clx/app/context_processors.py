from django.http import HttpRequest

from clx.app.models import SiteConfig
from clx.app.selectors.site_config import site_config_get


def site_config(request: HttpRequest) -> dict[str, SiteConfig]:
    """Expose the site config to every template."""
    return {"site_config": site_config_get()}
