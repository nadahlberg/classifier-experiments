from django.apps import AppConfig as DjangoAppConfig
from django.db.models.signals import post_migrate


class AppConfig(DjangoAppConfig):
    name = "clx.app"

    def ready(self) -> None:
        import clx.app.checks  # noqa: F401
        from clx.app.signals import (
            create_dev_user,
            create_site_config,
            sync_permissions_and_groups,
        )

        post_migrate.connect(create_site_config, sender=self)
        post_migrate.connect(sync_permissions_and_groups, sender=self)
        post_migrate.connect(create_dev_user, sender=self)
