import inspect
from typing import Any, ClassVar

from django.template.loader import render_to_string
from pydantic import BaseModel, ConfigDict

from clx.app.models import DemoChatThread

AGENTS: dict[str, type["Agent"]] = {}


class AgentState(BaseModel):
    """Base for an agent's per-thread state model."""

    model_config = ConfigDict(extra="allow")


class ToolOutput(BaseModel):
    """Result of running a tool."""

    result: str
    render_data: dict[str, Any] | None = None
    refresh_system_prompt: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


class Tool(BaseModel):
    """Base class for agent tools."""

    model_config = ConfigDict(extra="forbid")

    name: ClassVar[str]
    tool_call_template: ClassVar[str | bool | None] = None
    tool_result_template: ClassVar[str | bool | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.__doc__:
            raise TypeError(f"{cls.__name__} must have a docstring")

    def __call__(self, *, thread_id: str) -> ToolOutput:
        raise NotImplementedError

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": cls.name,
                "description": inspect.getdoc(cls) or "",
                "parameters": cls.model_json_schema(),
            },
        }


class Agent:
    """Base class for chat agents; subclassing registers by name."""

    name: ClassVar[str]
    model: ClassVar[str]
    max_tokens: ClassVar[int] = 4096
    max_steps: ClassVar[int] = 10
    compact_after_tokens: ClassVar[int] = 100_000
    state_template: ClassVar[str | None] = None
    tools: ClassVar[list[type[Tool]]] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.__doc__:
            raise TypeError(f"{cls.__name__} must have a docstring")
        AGENTS[cls.name] = cls

    def get_system_prompt(self, thread: DemoChatThread) -> str:
        raise NotImplementedError

    @property
    def tools_by_name(self) -> dict[str, type[Tool]]:
        return {tool.name: tool for tool in self.tools}

    @property
    def tool_schemas(self) -> list[dict[str, Any]] | None:
        return [tool.get_schema() for tool in self.tools] or None


def render_tool_call(
    tool: type[Tool] | None, args: dict[str, Any]
) -> dict[str, Any]:
    """Resolve a tool's call-card rendering directive."""
    return _render(tool.tool_call_template if tool else None, {"args": args})


def render_tool_result(
    tool: type[Tool] | None, render_data: dict[str, Any] | None
) -> dict[str, Any]:
    """Resolve a tool's result-card rendering directive."""
    template = tool.tool_result_template if tool else None
    return _render(template, {"data": render_data or {}})


def _render(
    template: str | bool | None, context: dict[str, Any]
) -> dict[str, Any]:
    if template is False:
        return {"render_mode": "skip"}
    if isinstance(template, str):
        return {
            "render_mode": "custom",
            "render_html": render_to_string(template, context),
        }
    return {"render_mode": "default"}
