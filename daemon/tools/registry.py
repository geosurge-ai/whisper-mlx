"""
Tool registry: discovers, loads, and executes tools.

Architecture:
- Tools are imported from dedicated modules (one tool per module)
- Registry provides unified interface for both LLM and direct API access
- Supports both sync and async tool functions
- Lazy loading for performance (tools loaded on first access)
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any

from .base import Tool, ToolSpec, ToolFunction

logger = logging.getLogger("qwen.tools")


class ToolRegistry:
    """
    Central registry for tool implementations.

    Provides:
    - Tool registration (direct or lazy)
    - Tool lookup by name
    - Sync and async execution
    - List of available tools and their specs
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._lazy_loaders: dict[str, tuple[str, str]] = (
            {}
        )  # name -> (module_path, attr)

    def register(self, tool: Tool) -> None:
        """Register a tool directly."""
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def register_lazy(self, name: str, module_path: str, attr: str = "TOOL") -> None:
        """
        Register a lazy loader for a tool.

        The tool module will be imported and the attr accessed on first use.
        """
        self._lazy_loaders[name] = (module_path, attr)
        logger.debug(f"Registered lazy tool: {name} -> {module_path}.{attr}")

    def _load_lazy(self, name: str) -> Tool | None:
        """Load a lazily-registered tool."""
        if name not in self._lazy_loaders:
            return None

        module_path, attr = self._lazy_loaders[name]
        try:
            import importlib

            module = importlib.import_module(module_path)
            tool = getattr(module, attr)
            if isinstance(tool, Tool):
                self._tools[name] = tool
                del self._lazy_loaders[name]
                logger.debug(f"Lazy-loaded tool: {name}")
                return tool
            else:
                logger.error(
                    f"Tool {name} at {module_path}.{attr} is not a Tool instance"
                )
                return None
        except Exception as e:
            logger.error(f"Failed to load tool {name}: {e}")
            return None

    def get(self, name: str) -> Tool | None:
        """Get a tool by name, loading lazily if needed."""
        if name in self._tools:
            return self._tools[name]
        return self._load_lazy(name)

    def get_spec(self, name: str) -> ToolSpec | None:
        """Get a tool's spec by name."""
        tool = self.get(name)
        return tool.spec if tool else None

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """
        Execute a SYNC tool by name with given arguments.

        Returns JSON string result or error.
        NOTE: For async tools, use execute_async() instead.
        """
        tool = self.get(name)
        if tool is None:
            return json.dumps({"error": f"Unknown tool: {name}"})

        try:
            result = tool.execute(**arguments)
            # If accidentally called on async tool, handle gracefully
            if inspect.iscoroutine(result):
                result.close()  # Prevent "coroutine never awaited" warning
                return json.dumps(
                    {"error": f"Tool {name} is async, use execute_async()"}
                )
            return result  # type: ignore
        except Exception as e:
            logger.exception(f"Tool {name} execution failed")
            return json.dumps({"error": f"Tool execution failed: {str(e)}"})

    async def execute_async(self, name: str, arguments: dict[str, Any]) -> str:
        """
        Execute a tool by name with given arguments (async-aware).

        Handles both sync and async tools:
        - Async tools are awaited directly
        - Sync tools are run in a thread pool to avoid blocking

        Returns JSON string result or error.
        """
        tool = self.get(name)
        if tool is None:
            return json.dumps({"error": f"Unknown tool: {name}"})

        try:
            if asyncio.iscoroutinefunction(tool.execute):
                # Async tool - await directly
                result: str = await tool.execute(**arguments)
            else:
                # Sync tool - run in thread pool to avoid blocking event loop
                result = await asyncio.to_thread(tool.execute, **arguments)
            return result
        except Exception as e:
            logger.exception(f"Tool {name} async execution failed")
            return json.dumps({"error": f"Tool execution failed: {str(e)}"})

    @property
    def available_tools(self) -> list[str]:
        """List all registered tool names (including lazy)."""
        return list(set(self._tools.keys()) | set(self._lazy_loaders.keys()))

    def get_all_specs(self) -> dict[str, ToolSpec]:
        """Get specs for all registered tools."""
        specs = {}
        for name in self.available_tools:
            spec = self.get_spec(name)
            if spec:
                specs[name] = spec
        return specs

    def get_tools(self, names: tuple[str, ...]) -> tuple[Tool, ...]:
        """Get multiple tools by name, filtering out missing ones."""
        tools = []
        for name in names:
            tool = self.get(name)
            if tool:
                tools.append(tool)
            else:
                logger.warning(f"Tool not found: {name}")
        return tuple(tools)

    def get_specs(self, names: tuple[str, ...]) -> tuple[ToolSpec, ...]:
        """Get specs for multiple tools by name."""
        return tuple(t.spec for t in self.get_tools(names))


# --- Global Registry Instance ---

_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get or create the global tool registry."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _populate_registry(_registry)
    return _registry


def _populate_registry(registry: ToolRegistry) -> None:
    """
    Populate registry with all available tools via lazy loading.

    Tools are loaded on-demand from their respective modules.
    """
    # Mirror tools
    mirror_tools = [
        "get_current_datetime",
        "run_python",
        "search_linear_issues",
        "get_linear_issue",
        "list_linear_events",
        "search_slack_messages",
        "get_slack_thread",
        "list_recent_slack_activity",
        "lookup_user",
    ]
    for name in mirror_tools:
        registry.register_lazy(name, f"daemon.tools.mirror.{name}", "TOOL")

    # Browser tools
    browser_tools = [
        "web_search",
        "browser_navigate",
        "browser_get_text",
        "browser_click",
        "browser_get_elements",
        "browser_wait",
        "browser_paste_code",
        "browser_type_slow",
        "browser_press_key",
        "browser_analyze_page",
    ]
    for name in browser_tools:
        registry.register_lazy(name, f"daemon.tools.browser.{name}", "TOOL")

    # OCR tools
    ocr_tools = [
        "ocr_document",
    ]
    for name in ocr_tools:
        registry.register_lazy(name, f"daemon.tools.ocr.{name}", "TOOL")

    # Google tools (Gmail, Calendar)
    google_tools = [
        "search_emails",
        "get_email",
        "search_calendar",
        "get_calendar_event",
    ]
    for name in google_tools:
        registry.register_lazy(name, f"daemon.tools.google.{name}", "TOOL")

    logger.info(f"Registry populated with {len(registry.available_tools)} tools (lazy)")
