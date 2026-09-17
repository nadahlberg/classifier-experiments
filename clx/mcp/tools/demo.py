from typing import Any

from mcp.types import ToolAnnotations

from clx.app.exceptions import ApplicationError
from clx.app.permissions import MANAGE_ADMIN
from clx.mcp.tools.base import MCPTool
from clx.mcp.utils import current_scopes, current_user

BURST_LIMIT = 5
BURST_WINDOW_SECONDS = 60


async def _whoami(note: str) -> dict[str, Any]:
    user = await current_user()
    if user is None:
        raise ApplicationError("No authenticated user")
    return {
        "note": note,
        "user": user.email,
        "scopes": list(current_scopes()),
    }


class AuthWhoamiTool(MCPTool):
    """Report who the server thinks you are.

    Returns the authenticated user's email and the scopes granted to the
    OAuth token this session presented. Call it to verify a connection is
    authenticated and to see which scopes the other auth demo tools will
    be checked against. Requires no particular scope or permission.
    """

    name = "auth_whoami"
    annotations = ToolAnnotations(
        title="Who Am I",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    async def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await _whoami("Any valid token; no scope required.")


class AuthScopedReadTool(MCPTool):
    """Demonstrate a read operation gated by the demo:read scope.

    Succeeds only when the OAuth token carries the demo:read scope, and
    the call is counted against the caller's demo:read rate budget — the
    same bucket the HTTP API's demo:read endpoints draw from. Use it to
    confirm a token was granted read access to the demo data.
    """

    name = "auth_scoped_read"
    required_scopes = ("demo:read",)
    annotations = ToolAnnotations(
        title="Scoped Read",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    async def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await _whoami("Requires scope demo:read.")


class AuthScopedWriteTool(MCPTool):
    """Demonstrate a write operation gated by the demo:write scope.

    Succeeds only when the OAuth token carries the demo:write scope, and
    the call is counted against the caller's demo:write rate budget — the
    same bucket the HTTP API's demo:write endpoints draw from. It writes
    nothing; it stands in for a tool that would.
    """

    name = "auth_scoped_write"
    required_scopes = ("demo:write",)
    annotations = ToolAnnotations(
        title="Scoped Write",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    async def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await _whoami("Requires scope demo:write.")


class AuthBurstTool(MCPTool):
    """Demonstrate a per-tool rate limit that is easy to hit.

    Allows five calls per minute per user, on top of the shared per-user
    and per-scope budgets every tool draws from. Call it repeatedly to
    see the rate-limit error an exhausted budget produces.
    """

    name = "auth_burst"
    rate = (BURST_LIMIT, BURST_WINDOW_SECONDS)
    annotations = ToolAnnotations(
        title="Burst Limit",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    async def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await _whoami(
            f"{BURST_LIMIT} calls per {BURST_WINDOW_SECONDS}s."
        )


class AuthAdminGatedTool(MCPTool):
    """Demonstrate a permission check enforced at the call, not the listing.

    This tool is listed for every caller, but calling it requires the
    app.manage_admin permission — without it the call is rejected. It is
    the counterpart to admin_status, which is hidden from the listing
    entirely when the caller lacks that permission.
    """

    name = "auth_admin_gated"
    required_perms = (MANAGE_ADMIN,)
    always_listed = True
    annotations = ToolAnnotations(
        title="Admin Gated",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    async def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await _whoami("Requires the app.manage_admin permission.")
