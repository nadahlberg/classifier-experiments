from django.contrib.auth.decorators import permission_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from clx.app.permissions import GROUPS, PERMISSIONS


@permission_required("app.manage_admin")
def settings(request: HttpRequest) -> HttpResponse:
    """Settings tab of the admin page."""
    return render(request, "pages/admin/settings.html")


@permission_required("app.manage_admin")
def users(request: HttpRequest) -> HttpResponse:
    """Users tab of the admin page."""
    return render(
        request,
        "pages/admin/users.html",
        {
            "groups": [
                {
                    "name": name,
                    "permissions": [
                        {
                            "codename": f"app.{codename}",
                            "description": PERMISSIONS[codename],
                        }
                        for codename in codenames
                    ],
                }
                for name, codenames in GROUPS.items()
            ],
        },
    )
