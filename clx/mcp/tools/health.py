from typing import Any

from asgiref.sync import sync_to_async
from mcp.types import ToolAnnotations
from pydantic import Field

from clx.app.services.health import ServiceName, health_check_services
from clx.mcp.tools.base import MCPTool, ToolInputs


class HealthInputs(ToolInputs):
    services: list[ServiceName] = Field(
        default=[],
        description="Services to check. Omit to check all of them.",
    )


class HealthTool(MCPTool):
    """Report whether the backing services are reachable."""

    name = "health"
    inputs = HealthInputs
    annotations = ToolAnnotations(
        title="Health Check",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    async def __call__(self, arguments: dict[str, Any]) -> dict[str, bool]:
        return await sync_to_async(health_check_services)(
            arguments.get("services")
        )
