import json
from typing import Any

from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware
from fastmcp.tools import ToolResult
from mcp.types import TextContent

from clx.app.api.utils.ratelimit import rate_limit_consume
from clx.app.exceptions import ApplicationError, RateLimitError
from clx.mcp.tools.base import TOOLS
from clx.mcp.utils import current_scopes, current_user, user_has_perms


class ToolMiddleware(Middleware):
    async def on_list_tools(self, context: Any, call_next: Any) -> Any:
        user = await current_user()
        return [
            tool.get_tool()
            for tool in TOOLS.values()
            if tool.always_listed
            or await user_has_perms(user, tool.required_perms)
        ]

    async def on_call_tool(self, context: Any, call_next: Any) -> ToolResult:
        tool = TOOLS.get(context.message.name)
        if tool is None:
            raise ToolError(f"Unknown tool: {context.message.name}")

        user = await current_user()
        if not await user_has_perms(user, tool.required_perms):
            raise ToolError("Permission denied")

        missing = set(tool.required_scopes) - set(current_scopes())
        if missing:
            raise ToolError(
                f"Token is missing scopes: {', '.join(sorted(missing))}"
            )

        if user is not None:
            try:
                await sync_to_async(rate_limit_consume)(
                    user_id=user.pk,
                    scopes=tool.required_scopes,
                    rate=tool.rate,
                )
            except RateLimitError as exc:
                raise ToolError(
                    f"{exc.message}; retry after {exc.retry_after}s"
                ) from exc

        arguments = context.message.arguments or {}
        tool.validate_arguments(arguments)

        try:
            result = await tool(arguments)
        except ApplicationError as exc:
            raise ToolError(exc.message) from exc
        except ValidationError as exc:
            raise ToolError("; ".join(exc.messages)) from exc

        if not isinstance(result, str):
            result = json.dumps(result, indent=2, default=str)
        return ToolResult(content=[TextContent(type="text", text=result)])
