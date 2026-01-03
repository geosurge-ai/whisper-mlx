"""
Centralized configuration for system prompts, tool definitions, and agent profiles.

Architecture:
- AgentProfile: immutable bundle of (system_prompt, tools, settings)
- ToolRegistry: central registry mapping tool names to implementations
- Prompts & tools are embedded in code per project requirements
"""

from dataclasses import dataclass
from typing import Any, Protocol
from enum import Enum


# --- Core Types ---


class ToolFunction(Protocol):
    """Protocol for tool implementations."""

    def __call__(self, **kwargs: Any) -> str: ...


@dataclass(frozen=True)
class ToolSpec:
    """
    Immutable tool specification.

    Separates the schema (for LLM) from the implementation (for execution).
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
class AgentProfile:
    """
    Immutable agent configuration bundle.

    Defines a specific "persona" with its system prompt, available tools,
    and inference settings.
    """

    name: str
    system_prompt: str
    tool_names: tuple[str, ...]  # References to tools in the registry
    max_tool_rounds: int = 8
    max_tokens: int = 4096
    temperature: float = 0.7


class ModelSize(Enum):
    """Available model sizes mapped to MLX model IDs."""

    SMALL = "mlx-community/Qwen2.5-7B-Instruct-4bit"  # ~5GB
    MEDIUM = "mlx-community/Qwen2.5-14B-Instruct-4bit"  # ~10GB
    LARGE = "mlx-community/Qwen3-32B-4bit"  # ~18GB


# --- System Prompts ---

MIRROR_SYSTEM_PROMPT = """You are a knowledge assistant with access to your team's Linear issues and Slack conversations.

## Your Data Sources

1. **Linear Mirror**: All issues, comments, and activity events from your Linear workspace
2. **Slack Mirror**: Conversations and threads from your Slack workspace

## How to Answer Questions

1. **Search first**: Use search tools to find relevant issues or messages before answering
2. **Drill down**: Use get_linear_issue or get_slack_thread for full details when needed
3. **Synthesize**: Combine information from multiple sources to give complete answers
4. **Be transparent**: Say when information might be incomplete or outdated (mirrors sync periodically)

## Tool Strategy

- For questions about project status → search_linear_issues + get_linear_issue
- For "what happened" questions → list_linear_events
- For conversation/discussion questions → search_slack_messages + get_slack_thread
- For people questions → lookup_user

## Response Style

- Be concise but thorough
- Cite specific issues (e.g., "According to FE-42...") or threads when relevant
- If results are paginated, mention there may be more results
- If you can't find relevant information, say so clearly

Remember: You're helping someone understand their team's work. Focus on actionable insights."""


CODE_RUNNER_SYSTEM_PROMPT = """You are a code runner agent. Your task is to run code in online playgrounds.

## Your Capabilities
- You can search the web to find online code playgrounds
- You can control a browser to navigate, click, and type
- You can write code in any programming language

## Finding Playgrounds
You do NOT have hardcoded playground URLs. You MUST use web_search to find an online interpreter for the requested language.
Search for: "[language] online interpreter run code"

## Workflow
1. web_search for "[language] online interpreter run code"
2. browser_navigate to best result (NOT documentation/GitHub)
3. browser_analyze_page to check readiness
4. If ready_for_code is TRUE:
   a. browser_paste_code with your complete code
   b. browser_click using EXACT selector from run_button_selectors (e.g. "button:has-text('Run')")
   c. browser_wait for 2 seconds
   d. browser_get_text to see output
5. If NOT ready: try another URL

CRITICAL: Use the EXACT selectors returned by browser_analyze_page! Do not guess.

## IMPORTANT WARNINGS
- A playground MUST have: (1) code input area, (2) Run/Execute button, (3) output area
- Documentation sites, wikis, and GitHub repos are NOT playgrounds!
- If the first site doesn't work, search again with different terms
- Write COMPLETE, working code - not pseudocode
- Always include necessary imports/includes
- Make sure the code is syntactically correct
- After running, tell the user what output you observed
- Do NOT close the browser - leave it open for the user"""


GENERAL_ASSISTANT_PROMPT = (
    """You are a helpful AI assistant. You answer questions clearly and concisely."""
)


# --- Tool Specifications ---

# Mirror tools (Linear/Slack knowledge base)
MIRROR_TOOL_SPECS = (
    ToolSpec(
        name="search_linear_issues",
        description="Search Linear issues by keyword. Supports filtering by state (e.g., 'In Progress'), assignee name, and label. Returns paginated summary results - use get_linear_issue for full details.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term to match in issue title or description. Leave empty for all issues.",
                },
                "state": {
                    "type": "string",
                    "description": "Filter by state name (e.g., 'Todo', 'In Progress', 'Done')",
                },
                "assignee": {
                    "type": "string",
                    "description": "Filter by assignee name (partial match)",
                },
                "label": {
                    "type": "string",
                    "description": "Filter by label name (partial match)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results per page (default 10)",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number for pagination (0-indexed)",
                },
            },
            "required": [],
        },
    ),
    ToolSpec(
        name="get_linear_issue",
        description="Get full details for a specific Linear issue by its identifier (e.g., FE-42, NIN-123). Returns description, comments, and all metadata.",
        parameters={
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": "The issue identifier like FE-42, NIN-123, GTM-15",
                },
            },
            "required": ["identifier"],
        },
    ),
    ToolSpec(
        name="list_linear_events",
        description="List recent Linear activity: state changes, assignments, comments, etc. Good for understanding what happened recently.",
        parameters={
            "type": "object",
            "properties": {
                "since_days": {
                    "type": "integer",
                    "description": "How many days back to look (default 7)",
                },
                "event_type": {
                    "type": "string",
                    "description": "Filter by event type (e.g., 'state', 'assignee', 'comment')",
                },
                "actor": {
                    "type": "string",
                    "description": "Filter by who made the change (name)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results per page (default 20)",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number for pagination (0-indexed)",
                },
            },
            "required": [],
        },
    ),
    ToolSpec(
        name="search_slack_messages",
        description="Search Slack messages across all channels and threads. Returns matching messages with context to drill down into specific threads.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term to match in message text",
                },
                "channel": {
                    "type": "string",
                    "description": "Optional channel ID to limit search (e.g., C08D0GTKWLD)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results per page (default 10)",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number for pagination (0-indexed)",
                },
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="get_slack_thread",
        description="Get the full conversation in a Slack thread. Use this after finding a relevant thread via search_slack_messages.",
        parameters={
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "The Slack channel ID (e.g., C08D0GTKWLD)",
                },
                "thread_ts": {
                    "type": "string",
                    "description": "The thread timestamp (e.g., 1700000000.123456)",
                },
            },
            "required": ["channel_id", "thread_ts"],
        },
    ),
    ToolSpec(
        name="lookup_user",
        description="Look up a user by ID or name to get their profile info. Works for both Linear and Slack users.",
        parameters={
            "type": "object",
            "properties": {
                "user_id_or_name": {
                    "type": "string",
                    "description": "User ID or name to search for",
                },
                "source": {
                    "type": "string",
                    "enum": ["linear", "slack", "both"],
                    "description": "Where to search: 'linear', 'slack', or 'both' (default)",
                },
            },
            "required": ["user_id_or_name"],
        },
    ),
)


# Browser/web tools (code runner)
BROWSER_TOOL_SPECS = (
    ToolSpec(
        name="web_search",
        description="Search the web using DuckDuckGo. Use this to find online code playgrounds for unfamiliar languages.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, e.g. 'Haskell online playground'",
                },
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="browser_navigate",
        description="Navigate browser to a URL. Returns page title and final URL.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to navigate to"},
            },
            "required": ["url"],
        },
    ),
    ToolSpec(
        name="browser_get_text",
        description="Get visible text content from the current page. Use to see output after running code.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name="browser_click",
        description="Click an element. Use CSS selector like 'button', '#run-btn' or visible text like 'Run'.",
        parameters={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector or visible text of element to click",
                },
            },
            "required": ["selector"],
        },
    ),
    ToolSpec(
        name="browser_get_elements",
        description="List clickable elements (buttons, links) on the page. Useful to find the Run button.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name="browser_wait",
        description="Wait for a number of seconds. Use after clicking Run to wait for execution.",
        parameters={
            "type": "object",
            "properties": {
                "seconds": {"type": "integer", "description": "Seconds to wait (1-10)"},
            },
            "required": ["seconds"],
        },
    ),
    ToolSpec(
        name="browser_paste_code",
        description="Paste code into the editor. Automatically finds the code editor, selects all, and pastes. Use this as the primary way to enter code.",
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The complete source code to paste",
                },
            },
            "required": ["code"],
        },
    ),
    ToolSpec(
        name="browser_type_slow",
        description="Type text character by character. Use as fallback if browser_paste_code fails.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type slowly"},
            },
            "required": ["text"],
        },
    ),
    ToolSpec(
        name="browser_press_key",
        description="Press a keyboard key like Enter, Tab, Escape, F5, etc.",
        parameters={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Key to press (Enter, Tab, Escape, F5, etc.)",
                },
            },
            "required": ["key"],
        },
    ),
    ToolSpec(
        name="browser_analyze_page",
        description="Analyze the current page to check if it has a code editor and run button. Returns structured info about whether the page is READY for code input. ALWAYS call this after navigating to a new page!",
        parameters={"type": "object", "properties": {}},
    ),
)


# --- Agent Profiles ---

AGENT_PROFILES: dict[str, AgentProfile] = {
    "mirror": AgentProfile(
        name="mirror",
        system_prompt=MIRROR_SYSTEM_PROMPT,
        tool_names=tuple(t.name for t in MIRROR_TOOL_SPECS),
        max_tool_rounds=8,
    ),
    "code_runner": AgentProfile(
        name="code_runner",
        system_prompt=CODE_RUNNER_SYSTEM_PROMPT,
        tool_names=tuple(t.name for t in BROWSER_TOOL_SPECS),
        max_tool_rounds=10,
    ),
    "general": AgentProfile(
        name="general",
        system_prompt=GENERAL_ASSISTANT_PROMPT,
        tool_names=(),
        max_tool_rounds=1,
    ),
}


# --- Tool Spec Registry ---

ALL_TOOL_SPECS: dict[str, ToolSpec] = {
    **{t.name: t for t in MIRROR_TOOL_SPECS},
    **{t.name: t for t in BROWSER_TOOL_SPECS},
}


def get_tools_for_profile(profile_name: str) -> tuple[ToolSpec, ...]:
    """Get tool specs for a given agent profile."""
    profile = AGENT_PROFILES.get(profile_name)
    if profile is None:
        return ()
    return tuple(
        ALL_TOOL_SPECS[name] for name in profile.tool_names if name in ALL_TOOL_SPECS
    )
