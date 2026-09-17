from typing import Any

from mcp.types import ToolAnnotations

from clx.app.exceptions import ApplicationError
from clx.app.permissions import MANAGE_ADMIN
from clx.mcp.tools.base import MCPTool, ToolInputs
from clx.mcp.utils import current_user


class AdminStatusInputs(ToolInputs):
    query: str


class AdminStatusTool(MCPTool):
    """Return the calling user's details alongside the given query."""

    name = "admin_status"
    inputs = AdminStatusInputs
    required_perms = (MANAGE_ADMIN,)
    annotations = ToolAnnotations(
        title="Admin Status",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    async def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        user = await current_user()
        if user is None:
            raise ApplicationError("No authenticated user")

        return {
            "query": arguments["query"],
            "user": {
                "id": user.pk,
                "email": user.email,
                "is_staff": user.is_staff,
            },
        }
