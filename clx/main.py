import os
from typing import cast

from django.core.asgi import get_asgi_application
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp


async def mcp_slash_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse("/mcp/", status_code=307)


def create_application() -> Starlette:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "clx.settings")
    django_app = cast(ASGIApp, get_asgi_application())

    from clx.mcp.server import auth, mcp

    mcp_app = mcp.http_app(path="/")

    metadata_routes = [
        route for route in auth.get_routes() if isinstance(route, Route)
    ]

    return Starlette(
        routes=[
            *metadata_routes,
            *[
                Route(
                    f"{route.path}/",
                    route.endpoint,
                    methods=sorted(route.methods or {"GET"}),
                )
                for route in metadata_routes
            ],
            Route(
                "/mcp",
                mcp_slash_redirect,
                methods=["GET", "POST", "DELETE", "OPTIONS"],
            ),
            Mount("/mcp", app=mcp_app),
            Mount("/", app=django_app),
        ],
        lifespan=mcp_app.lifespan,
    )


application = create_application()
