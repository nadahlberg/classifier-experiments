import os

from fastmcp import FastMCP
from fastmcp.server.auth import RemoteAuthProvider
from pydantic import AnyHttpUrl

from clx.app.permissions import API_SCOPES
from clx.mcp.auth import DjangoTokenVerifier
from clx.mcp.middleware import ToolMiddleware

DOMAIN = os.getenv("DOMAIN", "")
BASE_URL = f"https://{DOMAIN}" if DOMAIN else "http://localhost:8000"

auth = RemoteAuthProvider(
    token_verifier=DjangoTokenVerifier(),
    authorization_servers=[AnyHttpUrl(BASE_URL)],
    base_url=BASE_URL,
    resource_base_url=f"{BASE_URL}/mcp",
    scopes_supported=sorted(API_SCOPES),
)

mcp: FastMCP = FastMCP("clx", auth=auth)
mcp.add_middleware(ToolMiddleware())
