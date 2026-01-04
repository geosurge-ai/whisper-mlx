"""
Browser analyze page tool.

Analyze the current page for code editor and run button.
"""

import json
import logging
from typing import Any

from playwright.async_api import Error as PlaywrightError

from ..base import tool
from .manager import get_browser_manager

logger = logging.getLogger("qwen.browser")


@tool(
    name="browser_analyze_page",
    description="Analyze the current page to check if it has a code editor and run button. Returns structured info about whether the page is READY for code input. ALWAYS call this after navigating to a new page!",
    parameters={"type": "object", "properties": {}},
)
async def browser_analyze_page() -> str:
    """Analyze the current page for code editor and run button."""
    logger.info("[TOOL] browser_analyze_page")
    page = await get_browser_manager().ensure_browser()
    
    try:
        # Check for code editors
        editor_locator = (
            page.locator("textarea")
            .or_(page.locator(".ace_editor"))
            .or_(page.locator(".CodeMirror"))
            .or_(page.locator(".monaco-editor"))
        )
        
        editor_found: dict[str, str] | None = None
        editor_count = await editor_locator.count()
        if editor_count > 0:
            if await page.locator("textarea").count() > 0:
                editor_found = {"selector": "textarea", "type": "textarea"}
            elif await page.locator(".ace_editor").count() > 0:
                editor_found = {"selector": ".ace_editor", "type": "ACE editor"}
            elif await page.locator(".CodeMirror").count() > 0:
                editor_found = {"selector": ".CodeMirror", "type": "CodeMirror"}
            elif await page.locator(".monaco-editor").count() > 0:
                editor_found = {"selector": ".monaco-editor", "type": "Monaco editor"}

        # Check for run/execute buttons
        run_button_locator = (
            page.get_by_role("button", name="Run")
            .or_(page.get_by_role("button", name="Execute"))
            .or_(page.get_by_role("button", name="Submit"))
            .or_(page.get_by_role("button", name="Go"))
            .or_(page.locator("#run"))
            .or_(page.locator(".run-button"))
            .or_(page.locator("[data-testid='run']"))
        )
        
        run_button_found: dict[str, str] | None = None
        run_count = await run_button_locator.count()
        if run_count > 0:
            if await page.get_by_role("button", name="Run").count() > 0:
                run_button_found = {"selector": "button:has-text('Run')", "name": "Run"}
            elif await page.get_by_role("button", name="Execute").count() > 0:
                run_button_found = {"selector": "button:has-text('Execute')", "name": "Execute"}
            elif await page.get_by_role("button", name="Submit").count() > 0:
                run_button_found = {"selector": "button:has-text('Submit')", "name": "Submit"}
            elif await page.locator("#run").count() > 0:
                run_button_found = {"selector": "#run", "name": "run"}
            else:
                run_button_found = {"selector": "Run", "name": "Run button"}

        ready = editor_found is not None and run_button_found is not None

        result: dict[str, Any] = {
            "ready_for_code": ready,
            "editor": editor_found,
            "run_button": run_button_found,
        }

        if ready and run_button_found:
            result["action"] = f"READY! Use browser_paste_code, then browser_click with: {run_button_found['name']}"
        elif editor_found and not run_button_found:
            result["action"] = "Has editor but no Run button found. Try pressing Ctrl+Enter or look for other buttons."
        else:
            result["action"] = "NOT a playground. Go back and try a different URL."

        return json.dumps(result)
    except PlaywrightError as e:
        logger.error(f"[TOOL] browser_analyze_page error: {e}")
        return json.dumps({"status": "error", "message": str(e)})


TOOL = browser_analyze_page
