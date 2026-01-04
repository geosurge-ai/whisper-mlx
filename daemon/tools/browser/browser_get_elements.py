"""
Browser get elements tool.

List interactive elements on the page.
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
    name="browser_get_elements",
    description="List clickable elements (buttons, links) on the page. Useful to find the Run button.",
    parameters={"type": "object", "properties": {}},
)
async def browser_get_elements() -> str:
    """List interactive elements on page."""
    page = await get_browser_manager().ensure_browser()
    elements: list[dict[str, str]] = []

    try:
        # Get buttons
        buttons = page.get_by_role("button")
        button_count = await buttons.count()
        for i in range(min(button_count, 10)):
            try:
                btn = buttons.nth(i)
                text = await btn.inner_text(timeout=5000)
                text = text[:50].strip()
                if text:
                    elements.append({"type": "button", "text": text})
            except PlaywrightTimeout:
                pass

        # Get links
        links = page.get_by_role("link")
        link_count = await links.count()
        for i in range(min(link_count, 10)):
            try:
                link = links.nth(i)
                text = await link.inner_text(timeout=5000)
                text = text[:50].strip()
                if text:
                    elements.append({"type": "link", "text": text})
            except PlaywrightTimeout:
                pass

        return json.dumps(elements[:15])
    except PlaywrightError as e:
        logger.error(f"[TOOL] browser_get_elements error: {e}")
        return json.dumps({"status": "error", "message": str(e)})


TOOL = browser_get_elements
