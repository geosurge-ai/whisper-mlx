"""
Browser type slow tool.

Type text character by character.
"""

import json
import logging
import sys

from playwright.async_api import Error as PlaywrightError

from ..base import tool
from .manager import get_browser_manager

logger = logging.getLogger("qwen.browser")


@tool(
    name="browser_type_slow",
    description="Type text character by character. Use as fallback if browser_paste_code fails.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to type slowly"},
        },
        "required": ["text"],
    },
)
async def browser_type_slow(text: str) -> str:
    """Type text character by character."""
    logger.info(f"[TOOL] browser_type_slow: {len(text)} chars")
    page = await get_browser_manager().ensure_browser()
    try:
        mod_key = "Meta" if sys.platform == "darwin" else "Control"
        await page.keyboard.press(f"{mod_key}+a")
        await page.keyboard.type(text, delay=10)
        return json.dumps({"status": "success", "chars_typed": len(text)})
    except PlaywrightError as e:
        logger.error(f"[TOOL] browser_type_slow error: {e}")
        return json.dumps({"status": "error", "message": str(e)})


TOOL = browser_type_slow
