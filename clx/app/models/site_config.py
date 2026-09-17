import uuid

from django.db import models

from clx.app.models.base import BaseModel

SITE_CONFIG_ID = uuid.UUID(int=0)


class SiteConfig(BaseModel):
    id = models.UUIDField(
        primary_key=True, default=SITE_CONFIG_ID, editable=False
    )
    site_name = models.CharField(
        max_length=100, default="Classifier Experiments"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=SITE_CONFIG_ID),
                name="site_config_is_a_singleton",
            ),
        ]
