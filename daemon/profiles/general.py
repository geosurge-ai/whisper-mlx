"""
General profile: General-purpose assistant with all tools.

A versatile profile with access to web search, browser automation,
Linear, Slack, Python execution, and document OCR.
"""

from .base import Profile
from daemon.tools.mirror import (
    get_current_datetime,
    run_python,
    search_linear_issues,
    get_linear_issue,
    list_linear_events,
    search_slack_messages,
    get_slack_thread,
    list_recent_slack_activity,
    lookup_user,
)
from daemon.tools.browser import (
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
from daemon.tools.ocr import (
    ocr_document,
)


# --- System Prompt ---

SYSTEM_PROMPT = """You are a helpful AI assistant with access to a variety of tools.

## Your Capabilities

1. **Web Search**: Search the internet for current information
2. **Browser**: Navigate websites, extract content, interact with pages
3. **Linear**: Access project management data (issues, events, activity)
4. **Slack**: Search team conversations and threads
5. **Python**: Run code for calculations, data analysis, and visualizations
6. **OCR**: Extract text from images and PDF documents

## Tool Usage Guidelines

- Use `get_current_datetime` first when questions involve time periods
- Use `web_search` for current events, facts, or information not in your training data
- Use browser tools to explore specific websites when needed
- Use Linear/Slack tools for team-specific queries
- Use `run_python` for calculations, statistics, or data transformations
- Use `ocr_document` to extract text from images or PDFs (local processing)

## Response Style

- Be clear and concise
- Cite sources when using web search results
- Show your reasoning when using multiple tools
- If a tool fails, explain what happened and try alternatives"""


# --- Tools ---

TOOLS = (
    # Time & Python
    get_current_datetime,
    run_python,
    # Web & Browser
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
    # Linear
    search_linear_issues,
    get_linear_issue,
    list_linear_events,
    # Slack
    search_slack_messages,
    get_slack_thread,
    list_recent_slack_activity,
    lookup_user,
    # OCR
    ocr_document,
)


# --- Profile Definition ---

PROFILE = Profile(
    name="general",
    system_prompt=SYSTEM_PROMPT,
    tools=TOOLS,
    max_tool_rounds=8,
    max_tokens=4096,
)
