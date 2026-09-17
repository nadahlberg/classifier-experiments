from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def index(request: HttpRequest) -> HttpResponse:
    """Index page."""
    return render(request, "pages/index.html")


@login_required
def profile(request: HttpRequest) -> HttpResponse:
    """Profile page."""
    return render(request, "pages/profile.html")


@login_required
def components(request: HttpRequest) -> HttpResponse:
    """Components library page."""
    return render(request, "pages/components.html")
