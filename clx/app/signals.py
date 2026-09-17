from typing import Any

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from clx.app.models import SITE_CONFIG_ID, SiteConfig, User
from clx.app.permissions import GROUPS, PERMISSIONS
from clx.app.services.user import user_create


def create_site_config(sender: Any, **kwargs: Any) -> None:
    SiteConfig.objects.get_or_create(id=SITE_CONFIG_ID)


def sync_permissions_and_groups(sender: Any, **kwargs: Any) -> None:
    ContentType.objects.clear_cache()
    content_type = ContentType.objects.get_for_model(User)

    permissions = {}
    for codename, name in PERMISSIONS.items():
        permission, _ = Permission.objects.get_or_create(
            codename=codename,
            content_type=content_type,
            defaults={"name": name},
        )
        permissions[codename] = permission

    for group_name, codenames in GROUPS.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        group.permissions.set(
            [permissions[codename] for codename in codenames]
        )


def create_dev_user(sender: Any, **kwargs: Any) -> None:
    email = settings.DEV_USER_EMAIL
    password = settings.DEV_USER_PASSWORD

    if not email or not password:
        return

    if User.objects.filter(email__iexact=email).exists():
        return

    user = user_create(email=email, password=password)
    EmailAddress.objects.create(
        user=user,
        email=user.email,
        primary=True,
        verified=True,
    )
    user.groups.add(Group.objects.get(name="Developer"))
