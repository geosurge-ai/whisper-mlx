"""
Tool registry and executor implementations.

Architecture:
- ToolRegistry: singleton mapping tool names -> callable implementations
- Tool implementations are imported from existing agents or defined here
- Registry is populated at daemon startup
"""

from __future__ import annotations

import json
from typing import Any, Callable


# Type alias for tool functions
ToolFunction = Callable[..., str]
ToolLoader = Callable[[], dict[str, ToolFunction]]


class ToolRegistry:
    """
    Central registry for tool implementations.

    Separates tool schemas (in config.py) from implementations (here).
    Allows dynamic registration and lazy loading of tool implementations.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolFunction] = {}
        self._lazy_loaders: dict[str, Callable[[], ToolFunction]] = {}

    def register(self, name: str, func: ToolFunction) -> None:
        """Register a tool implementation directly."""
        self._tools[name] = func

    def register_lazy(self, name: str, loader: Callable[[], ToolFunction]) -> None:
        """Register a lazy loader that will be invoked on first use."""
        self._lazy_loaders[name] = loader

    def get(self, name: str) -> ToolFunction | None:
        """Get a tool by name, invoking lazy loader if needed."""
        if name in self._tools:
            return self._tools[name]

        if name in self._lazy_loaders:
            self._tools[name] = self._lazy_loaders[name]()
            del self._lazy_loaders[name]
            return self._tools[name]

        return None

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """
        Execute a tool by name with given arguments.

        Returns JSON string result or error.
        """
        tool = self.get(name)
        if tool is None:
            return json.dumps({"error": f"Unknown tool: {name}"})

        try:
            result: str = tool(**arguments)
            return result
        except Exception as e:
            return json.dumps({"error": f"Tool execution failed: {str(e)}"})

    @property
    def available_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(set(self._tools.keys()) | set(self._lazy_loaders.keys()))


# --- Global Registry Instance ---

_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get or create the global tool registry."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _populate_registry(_registry)
    return _registry


# --- Mirror Tool Implementations ---
# These are imported from the existing mirror_agent module


def _create_mirror_tools_loader() -> ToolLoader:
    """Create lazy loaders for mirror tools."""
    _cache: dict[str, ToolFunction] = {}

    def load_mirror_tools() -> dict[str, ToolFunction]:
        if _cache:
            return _cache

        # Import mirror_agent to get implementations
        # We do this lazily to avoid loading data until needed
        try:
            from mirror_agent import (
                search_linear_issues,
                get_linear_issue,
                list_linear_events,
                search_slack_messages,
                get_slack_thread,
                lookup_user,
            )

            _cache.update(
                {
                    "search_linear_issues": search_linear_issues,
                    "get_linear_issue": get_linear_issue,
                    "list_linear_events": list_linear_events,
                    "search_slack_messages": search_slack_messages,
                    "get_slack_thread": get_slack_thread,
                    "lookup_user": lookup_user,
                }
            )
        except ImportError as e:
            # Return stub functions if mirror_agent not available
            err_msg = str(e)

            def make_stub(error: str) -> ToolFunction:
                def stub(**kwargs: Any) -> str:
                    return json.dumps({"error": f"mirror_agent not available: {error}"})

                return stub

            for name in [
                "search_linear_issues",
                "get_linear_issue",
                "list_linear_events",
                "search_slack_messages",
                "get_slack_thread",
                "lookup_user",
            ]:
                _cache[name] = make_stub(err_msg)

        return _cache

    return load_mirror_tools


def _create_browser_tools_loader() -> ToolLoader:
    """Create lazy loaders for browser tools."""
    _cache: dict[str, ToolFunction] = {}

    def load_browser_tools() -> dict[str, ToolFunction]:
        if _cache:
            return _cache

        try:
            from code_runner_agent import (
                web_search,
                browser_navigate,
                browser_get_text,
                browser_click,
                browser_get_elements,
                browser_wait,
                browser_paste_code,
                browser_type_slow,
                browser_press_key,
                browser_analyze_page,
            )

            _cache.update(
                {
                    "web_search": web_search,
                    "browser_navigate": browser_navigate,
                    "browser_get_text": browser_get_text,
                    "browser_click": browser_click,
                    "browser_get_elements": browser_get_elements,
                    "browser_wait": browser_wait,
                    "browser_paste_code": browser_paste_code,
                    "browser_type_slow": browser_type_slow,
                    "browser_press_key": browser_press_key,
                    "browser_analyze_page": browser_analyze_page,
                }
            )
        except ImportError as e:
            err_msg = str(e)

            def make_stub(error: str) -> ToolFunction:
                def stub(**kwargs: Any) -> str:
                    return json.dumps(
                        {"error": f"code_runner_agent not available: {error}"}
                    )

                return stub

            for name in [
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
            ]:
                _cache[name] = make_stub(err_msg)

        return _cache

    return load_browser_tools


# --- Registry Population ---


def _populate_registry(registry: ToolRegistry) -> None:
    """Populate registry with all available tools."""

    # Create lazy loaders
    mirror_loader = _create_mirror_tools_loader()
    browser_loader = _create_browser_tools_loader()

    # Register mirror tools with lazy loading
    for name in [
        "search_linear_issues",
        "get_linear_issue",
        "list_linear_events",
        "search_slack_messages",
        "get_slack_thread",
        "lookup_user",
    ]:
        registry.register_lazy(name, lambda n=name, loader=mirror_loader: loader()[n])

    # Register browser tools with lazy loading
    for name in [
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
    ]:
        registry.register_lazy(name, lambda n=name, loader=browser_loader: loader()[n])


# --- Standalone Test ---

if __name__ == "__main__":
    registry = get_registry()
    print("Available tools:", registry.available_tools)

    # Test a simple tool execution
    result = registry.execute("search_linear_issues", {"query": "test", "limit": 5})
    print(f"\nTest search result: {result[:200]}...")
