"""
Tools package: Self-contained, locally-invokable tool modules.

Architecture:
- Each tool is a module exporting a TOOL constant (base.Tool instance)
- Registry discovers and manages all tools
- Profiles import tools by name, don't define them

Public API:
- Tool, ToolSpec: Core types
- tool: Decorator for creating tools from functions
- get_registry: Access the global tool registry
- ToolRegistry: Registry class for custom registries
"""

from .base import Tool, ToolSpec, tool, ToolFunction
from .registry import ToolRegistry, get_registry

__all__ = [
    "Tool",
    "ToolSpec",
    "tool",
    "ToolFunction",
    "ToolRegistry",
    "get_registry",
]
