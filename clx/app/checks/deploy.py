from collections.abc import Sequence
from typing import Any

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import CheckMessage, Error, Tags, register


@register(Tags.staticfiles, deploy=True)
def check_file_serving(
    app_configs: Sequence[AppConfig] | None, **kwargs: Any
) -> list[CheckMessage]:
    """A serving process needs DEBUG or S3 to support file-serving."""
    if not settings.DEBUG and not settings.USE_S3:
        return [
            Error(
                "DEBUG=off with USE_S3=off leaves nothing serving static "
                "or media files - every asset would 404.",
                hint="Set USE_S3=on, or DEBUG=on for local development.",
                id="app.E001",
            )
        ]
    return []
