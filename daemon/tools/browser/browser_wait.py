"""
Browser wait tool.

Wait for a specified number of seconds.
"""

import json
import logging

from ..base import tool
from .manager import get_browser_manager

logger = logging.getLogger("qwen.browser")


@tool(
    name="browser_wait",
    description="Wait for a number of seconds. Use after clicking Run to wait for execution.",
    parameters={
        "type": "object",
        "properties": {
            "seconds": {"type": "integer", "description": "Seconds to wait (1-10)"},
        },
        "required": ["seconds"],
    },
)
async def browser_wait(seconds: int) -> str:
    """Wait for specified seconds."""
    if seconds > 300:
        logger.warning(f"[TOOL] browser_wait: capping {seconds}s to 300s max")
        seconds = 300
    page = await get_browser_manager().ensure_browser()
    await page.wait_for_timeout(seconds * 1000)
    return f"Waited {seconds} seconds"


TOOL = browser_wait
