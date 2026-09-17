from django.contrib.auth.models import Group

from clx.app.exceptions import ApplicationError
from clx.app.models import DemoUpload, User
from clx.app.selectors.user import USER_LEVELS, user_level

LEVEL_GROUPS = {"basic": [], "admin": ["Admin"], "developer": ["Developer"]}


def user_create(*, email: str, password: str | None = None) -> User:
    """Create a user."""
    user = User(email=email)
    user.set_password(password)
    user.full_clean()
    user.save()
    return user


def user_update(*, user: User, first_name: str, last_name: str) -> User:
    """Update a user's profile fields."""
    user.first_name = first_name.strip()
    user.last_name = last_name.strip()
    user.full_clean()
    user.save(update_fields=["first_name", "last_name"])
    return user


def user_level_set(*, actor: User, user: User, level: str) -> User:
    """Set a user's permission level to exactly basic, admin, or developer."""
    if level not in USER_LEVELS:
        raise ApplicationError(f"Unknown level: {level}")
    if actor == user:
        raise ApplicationError("You cannot change your own level")
    actor_rank = USER_LEVELS.index(user_level(actor))
    if USER_LEVELS.index(level) > actor_rank:
        raise ApplicationError("You cannot grant a level above your own")
    if USER_LEVELS.index(user_level(user)) > actor_rank:
        raise ApplicationError("You cannot change a user above your own level")
    user.groups.set(Group.objects.filter(name__in=LEVEL_GROUPS[level]))
    return user


def user_delete(user: User) -> None:
    """Delete a user, their rows, and every file they have in the bucket."""
    for upload in DemoUpload.objects.filter(user=user):
        upload.file.delete(save=False)
    user.delete()
