"""
Browser paste code tool.

Paste code into the active editor.
"""

import json
import logging
import sys

from playwright.async_api import (
    TimeoutError as PlaywrightTimeout,
    Error as PlaywrightError,
)

from ..base import tool
from .manager import get_browser_manager

logger = logging.getLogger("qwen.browser")


@tool(
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
)
async def browser_paste_code(code: str) -> str:
    """Paste code into the active editor."""
    logger.info(f"[TOOL] browser_paste_code: {len(code)} chars")
    page = await get_browser_manager().ensure_browser()
    
    try:
        # Strategy 1: Try textarea with fill()
        textarea = page.locator("textarea").first
        try:
            await textarea.wait_for(state="visible", timeout=5000)
            await textarea.fill(code, timeout=30000)
            logger.info(f"[TOOL] browser_paste_code: filled {len(code)} chars via fill()")
            return json.dumps({"status": "success", "code_length": len(code), "method": "fill"})
        except PlaywrightTimeout:
            logger.debug("[TOOL] No fillable textarea found, trying other editors")

        # Strategy 2: Try specialized code editors
        editor_locator = (
            page.locator(".ace_text-input")
            .or_(page.locator(".monaco-editor textarea"))
            .or_(page.locator(".CodeMirror textarea"))
            .or_(page.locator("[contenteditable=true]"))
        )
        
        try:
            await editor_locator.first.click(timeout=10000)
        except PlaywrightTimeout:
            viewport = page.viewport_size
            if viewport:
                await page.mouse.click(viewport["width"] // 2, viewport["height"] // 3)

        # Select all and delete
        mod_key = "Meta" if sys.platform == "darwin" else "Control"
        await page.keyboard.press(f"{mod_key}+a")
        await page.keyboard.press("Backspace")

        # Strategy 3: Clipboard paste
        try:
            await page.evaluate("text => navigator.clipboard.writeText(text)", code)
            await page.keyboard.press(f"{mod_key}+v")
            logger.info(f"[TOOL] browser_paste_code: pasted {len(code)} chars via clipboard")
            return json.dumps({"status": "success", "code_length": len(code), "method": "clipboard"})
        except PlaywrightError as paste_err:
            logger.warning(f"[TOOL] Clipboard paste failed: {paste_err}")

        # Strategy 4: Fall back to typing
        await page.keyboard.type(code, delay=1)
        logger.info(f"[TOOL] browser_paste_code: typed {len(code)} chars")
        return json.dumps({"status": "success", "code_length": len(code), "method": "typing"})

    except PlaywrightTimeout as e:
        logger.error(f"[TOOL] browser_paste_code timeout: {e}")
        return json.dumps({"status": "error", "message": "Operation timed out"})
    except PlaywrightError as e:
        logger.error(f"[TOOL] browser_paste_code error: {e}")
        return json.dumps({"status": "error", "message": str(e)})


TOOL = browser_paste_code
