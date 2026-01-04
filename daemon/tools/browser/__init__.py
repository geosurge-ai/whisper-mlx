"""
Browser tools package: Playwright-based web automation tools.

Each submodule exports a TOOL constant that can be imported by profiles.
All tools are async to work with Playwright's async API.
"""

# Import all tools for convenient access
from .web_search import TOOL as web_search
from .browser_navigate import TOOL as browser_navigate
from .browser_get_text import TOOL as browser_get_text
from .browser_click import TOOL as browser_click
from .browser_get_elements import TOOL as browser_get_elements
from .browser_wait import TOOL as browser_wait
from .browser_paste_code import TOOL as browser_paste_code
from .browser_type_slow import TOOL as browser_type_slow
from .browser_press_key import TOOL as browser_press_key
from .browser_analyze_page import TOOL as browser_analyze_page

# All tools exported from this package
ALL_TOOLS = (
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

__all__ = [
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
    "ALL_TOOLS",
]
