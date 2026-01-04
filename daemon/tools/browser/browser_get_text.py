"""
Browser get text tool.

Get visible text content from the current page.
"""

import json
import logging

from playwright.async_api import (
    TimeoutError as PlaywrightTimeout,
    Error as PlaywrightError,
)

from ..base import tool
from .manager import get_browser_manager

logger = logging.getLogger("qwen.browser")


@tool(
    name="browser_get_text",
    description="Get visible text content from the current page. Use to see output after running code.",
    parameters={"type": "object", "properties": {}},
)
async def browser_get_text() -> str:
    """Get visible text content from page."""
    page = await get_browser_manager().ensure_browser()
    try:
        body = page.locator("body")
        await body.wait_for(state="attached", timeout=30000)
        text = await body.inner_text(timeout=30000)
        return text[:3000] if len(text) > 3000 else text
    except PlaywrightTimeout:
        logger.error("[TOOL] browser_get_text: timeout waiting for page content")
        return json.dumps({"status": "error", "message": "Timeout getting page text"})
    except PlaywrightError as e:
        logger.error(f"[TOOL] browser_get_text error: {e}")
        return json.dumps({"status": "error", "message": str(e)})


TOOL = browser_get_text
