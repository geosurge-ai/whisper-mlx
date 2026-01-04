"""
Base types and protocols for the tool system.

Each tool is a self-contained module exporting a `TOOL` object that bundles
the schema (for LLM) with the implementation (for execution).

This architecture enables:
- Local-only tool API: Each tool invokable directly via HTTP
- Profile composition: Profiles import tool modules, don't define tools
- Clean separation: Spec and implementation co-located in one module
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Protocol, runtime_checkable


# Type alias for tool functions (sync or async)
ToolFunction = Callable[..., str | Coroutine[Any, Any, str]]


@dataclass(frozen=True)
class ToolSpec:
    """
    Immutable tool specification (schema only).
    
    This is what gets sent to the LLM for function calling.
    """
    name: str
    description: str
    parameters: dict[str, Any]

    def to_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema format for LLM prompt injection."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass(frozen=True)
class Tool:
    """
    Complete tool definition: schema + implementation.
    
    Each tool module exports a single `TOOL` instance of this type.
    The registry collects these and makes them available for:
    - LLM function calling (via spec)
    - Direct API invocation (via execute)
    """
    spec: ToolSpec
    execute: ToolFunction

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def description(self) -> str:
        return self.spec.description

    @property
    def parameters(self) -> dict[str, Any]:
        return self.spec.parameters

    def to_schema(self) -> dict[str, Any]:
        return self.spec.to_schema()


@runtime_checkable
class ToolModule(Protocol):
    """
    Protocol for tool modules.
    
    Each tool module must export a TOOL constant of type Tool.
    """
    TOOL: Tool


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
) -> Callable[[ToolFunction], Tool]:
    """
    Decorator to create a Tool from a function.
    
    Usage:
        @tool(
            name="get_weather",
            description="Get weather for a city",
            parameters={...}
        )
        def get_weather(city: str) -> str:
            return json.dumps({"temp": 22, "city": city})
        
        # get_weather is now a Tool instance
        TOOL = get_weather
    """
    def decorator(fn: ToolFunction) -> Tool:
        spec = ToolSpec(name=name, description=description, parameters=parameters)
        return Tool(spec=spec, execute=fn)
    return decorator
