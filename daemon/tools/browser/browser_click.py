"""
Browser click tool.

Click an element by selector or text.
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
)
async def browser_click(selector: str) -> str:
    """Click element by selector or text."""
    logger.info(f"[TOOL] browser_click: {selector}")
    page = await get_browser_manager().ensure_browser()
    
    try:
        locator = (
            page.get_by_role("button", name=selector)
            .or_(page.get_by_role("link", name=selector))
            .or_(page.get_by_text(selector, exact=False))
            .or_(page.locator(selector))
        )
        
        await locator.first.click(timeout=30000)
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
        
        return json.dumps({"status": "clicked", "selector": selector})
    except PlaywrightTimeout:
        logger.warning(f"[TOOL] browser_click: element not found: {selector}")
        return json.dumps({"status": "error", "message": f"Element not found: {selector}"})
    except PlaywrightError as e:
        logger.error(f"[TOOL] browser_click error: {e}")
        return json.dumps({"status": "error", "message": str(e)})


TOOL = browser_click
