"""
Browser press key tool.

Press a keyboard key.
"""

import json
import logging

from playwright.async_api import Error as PlaywrightError

from ..base import tool
from .manager import get_browser_manager

logger = logging.getLogger("qwen.browser")


@tool(
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
)
async def browser_press_key(key: str) -> str:
    """Press a keyboard key."""
    logger.info(f"[TOOL] browser_press_key: {key}")
    page = await get_browser_manager().ensure_browser()
    try:
        await page.keyboard.press(key)
        return json.dumps({"status": "pressed", "key": key})
    except PlaywrightError as e:
        logger.error(f"[TOOL] browser_press_key error: {e}")
        return json.dumps({"status": "error", "message": str(e)})


TOOL = browser_press_key
