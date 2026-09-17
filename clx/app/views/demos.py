from typing import cast

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from clx.app.permissions import API_SCOPES, PERMISSIONS, scope_rate_limit
from clx.app.services.demo import MAX_UPLOAD_FILES, MAX_UPLOAD_SIZE


@login_required
def index(request: HttpRequest) -> HttpResponse:
    """Demos page."""
    return render(request, "pages/demos/index.html")


@login_required
def celery(request: HttpRequest) -> HttpResponse:
    """Celery demo page."""
    schedule = cast(
        "float", settings.CELERY_BEAT_SCHEDULE["demo-heartbeat"]["schedule"]
    )
    return render(
        request,
        "pages/demos/celery.html",
        {"heartbeat_seconds": int(schedule)},
    )


@login_required
def uploads(request: HttpRequest) -> HttpResponse:
    """File uploads demo page."""
    return render(
        request,
        "pages/demos/uploads.html",
        {
            "max_files": MAX_UPLOAD_FILES,
            "max_size_mb": MAX_UPLOAD_SIZE // (1024 * 1024),
        },
    )


@login_required
def markdown(request: HttpRequest) -> HttpResponse:
    """Markdown editor demo page."""
    return render(request, "pages/demos/markdown.html")


@login_required
def components(request: HttpRequest) -> HttpResponse:
    """Components library demo page."""
    return render(request, "pages/demos/components.html")


@login_required
def search(request: HttpRequest) -> HttpResponse:
    """Search demo page."""
    return render(request, "pages/demos/search.html")


@login_required
def api(request: HttpRequest) -> HttpResponse:
    """API authentication demo page."""
    return render(
        request,
        "pages/demos/api.html",
        {
            "scopes": [
                {
                    "name": name,
                    "description": description,
                    "limit": scope_rate_limit(name),
                }
                for name, description in API_SCOPES.items()
            ],
            "max_lifetime_days": settings.API_TOKEN_MAX_LIFETIME_DAYS,
            "per_user_limit": settings.API_RATE_LIMIT_PER_USER,
            "per_session_limit": settings.API_RATE_LIMIT_PER_SESSION,
            "default_scope_limit": settings.API_RATE_LIMIT_PER_SCOPE_DEFAULT,
            "permissions": [
                {
                    "name": f"app.{codename}",
                    "description": description,
                    "granted": request.user.has_perm(f"app.{codename}"),
                }
                for codename, description in PERMISSIONS.items()
            ],
        },
    )
