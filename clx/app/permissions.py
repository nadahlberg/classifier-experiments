from django.conf import settings

MANAGE_ADMIN = "app.manage_admin"
MANAGE_DEVELOPER = "app.manage_developer"

PERMISSIONS = {
    "manage_admin": "Can manage admin",
    "manage_developer": "Can manage developer",
}

GROUPS = {
    "Admin": ["manage_admin"],
    "Developer": ["manage_admin", "manage_developer"],
}

API_SCOPES = {
    "demo:read": "Read demo data",
    "demo:write": "Create and modify demo data",
    "profile:read": "Read your profile",
}


def scope_rate_limit(scope: str) -> int:
    """The request budget configured for one scope."""
    return int(
        settings.API_RATE_LIMIT_PER_SCOPE.get(
            scope, settings.API_RATE_LIMIT_PER_SCOPE_DEFAULT
        )
    )
