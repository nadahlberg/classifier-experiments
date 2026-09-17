from typing import TypedDict

from django.core.paginator import Paginator
from django.db.models import Q

from clx.app.models import User

USER_LEVELS = ("basic", "admin", "developer")
USERS_PER_PAGE = 6


class UserPage(TypedDict):
    users: list[User]
    page: int
    pages: int
    total: int


def user_level(user: User) -> str:
    """The user's effective permission level, highest group wins."""
    if user.is_superuser:
        return "developer"
    names = {group.name for group in user.groups.all()}
    if "Developer" in names:
        return "developer"
    if "Admin" in names:
        return "admin"
    return "basic"


def user_search(
    *, query: str = "", level: str = "", page: int = 1
) -> UserPage:
    """One page of users by email search and level, newest signup first."""
    users = User.objects.prefetch_related("groups").order_by(
        "-date_joined", "id"
    )
    if query:
        users = users.filter(email__icontains=query.strip())
    if level == "developer":
        users = users.filter(
            Q(groups__name="Developer") | Q(is_superuser=True)
        ).distinct()
    elif level == "admin":
        users = users.filter(groups__name="Admin", is_superuser=False)
        users = users.exclude(groups__name="Developer").distinct()
    elif level == "basic":
        users = users.filter(is_superuser=False).exclude(
            groups__name__in=["Admin", "Developer"]
        )
    paginator = Paginator(users, USERS_PER_PAGE)
    page_obj = paginator.get_page(page)
    return {
        "users": list(page_obj.object_list),
        "page": page_obj.number,
        "pages": paginator.num_pages,
        "total": paginator.count,
    }
