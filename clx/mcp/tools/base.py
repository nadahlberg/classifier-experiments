import inspect
from functools import cached_property
from typing import Any, ClassVar

from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from jsonschema import Draft202012Validator
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict

TOOLS: dict[str, "MCPTool"] = {}


class ToolInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MCPTool:
    name: ClassVar[str]
    inputs: ClassVar[type[ToolInputs]] = ToolInputs
    required_perms: ClassVar[tuple[str, ...]] = ()
    required_scopes: ClassVar[tuple[str, ...]] = ()
    always_listed: ClassVar[bool] = False
    rate: ClassVar[tuple[int, int] | None] = None
    annotations: ClassVar[ToolAnnotations | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.__doc__:
            raise TypeError(f"{cls.__name__} must have a docstring")
        TOOLS[cls.name] = cls()

    def get_tool(self) -> Tool:
        return Tool(
            name=self.name,
            description=inspect.getdoc(self),
            parameters=self.input_schema,
            annotations=self.annotations,
        )

    def get_input_schema(self) -> dict[str, Any]:
        return self.inputs.model_json_schema()

    @cached_property
    def input_schema(self) -> dict[str, Any]:
        return self.get_input_schema()

    @cached_property
    def validator(self) -> Draft202012Validator:
        return Draft202012Validator(self.input_schema)

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        errors = sorted(
            self.validator.iter_errors(arguments),
            key=lambda error: list(error.path),
        )
        if not errors:
            return

        messages = []
        for error in errors:
            location = ".".join(str(part) for part in error.path)
            prefix = f"{location}: " if location else ""
            messages.append(f"{prefix}{error.message}")

        raise ToolError(
            f"Invalid arguments for tool '{self.name}':\n- "
            + "\n- ".join(messages)
        )

    async def __call__(self, arguments: dict[str, Any]) -> Any:
        raise NotImplementedError
