from asgiref.sync import sync_to_async
from fastmcp.server.dependencies import get_access_token

from clx.app.models import User


def _user_from_id(user_id: str) -> User | None:
    return User.objects.filter(pk=user_id, is_active=True).first()


def _has_perms(user: User, perms: tuple[str, ...]) -> bool:
    return all(user.has_perm(perm) for perm in perms)


async def current_user() -> User | None:
    token = get_access_token()
    if token is None or token.subject is None:
        return None
    return await sync_to_async(_user_from_id)(token.subject)


def current_scopes() -> tuple[str, ...]:
    token = get_access_token()
    if token is None:
        return ()
    return tuple(token.scopes)


async def user_has_perms(user: User | None, perms: tuple[str, ...]) -> bool:
    if not perms:
        return True
    if user is None:
        return False
    return await sync_to_async(_has_perms)(user, perms)
