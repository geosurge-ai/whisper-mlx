"""
Async browser tools for the Code_runner profile.

Uses Playwright's async API to avoid conflicts with FastAPI's asyncio event loop.
Provides a shared browser instance (visible, non-headless) for all sessions.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from playwright.async_api import async_playwright, Browser, Page, Playwright

from ddgs import DDGS

logger = logging.getLogger("qwen.browser")


# --- Browser Manager (Singleton) ---


class BrowserManager:
    """
    Manages a single shared browser instance.
    
    Lazy initialization - browser is created on first tool use.
    All sessions share the same browser context for simplicity.
    """

    _instance: BrowserManager | None = None

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    @classmethod
    def get_instance(cls) -> BrowserManager:
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def ensure_browser(self) -> Page:
        """Ensure browser is running and return the page."""
        if self._page is None:
            logger.info("🌐 Launching browser (visible mode)...")
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=False)
            self._page = await self._browser.new_page()
            logger.info("✅ Browser ready")
        return self._page

    async def close(self) -> None:
        """Close browser and cleanup resources."""
        if self._browser is not None:
            logger.info("🌐 Closing browser...")
            await self._browser.close()
            self._browser = None
            self._page = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
            logger.info("✅ Browser closed")

    @property
    def is_running(self) -> bool:
        """Check if browser is currently running."""
        return self._page is not None


def get_browser_manager() -> BrowserManager:
    """Get the singleton BrowserManager instance."""
    return BrowserManager.get_instance()


# --- Web Search Tool ---


async def web_search(query: str) -> str:
    """Search the web using DuckDuckGo and return top results."""
    logger.info(f"[TOOL] web_search: {query}")
    try:
        # DuckDuckGo search is sync, but fast enough to run directly
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))

        if not results:
            logger.info("[TOOL] web_search: no results")
            return json.dumps({"status": "no_results", "query": query})

        formatted = [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", "")[:200],
            }
            for r in results
        ]
        logger.info(f"[TOOL] web_search: found {len(formatted)} results")
        return json.dumps({"status": "success", "results": formatted})
    except Exception as e:
        logger.error(f"[TOOL] web_search ERROR: {e}")
        return json.dumps({"status": "error", "message": str(e)})


# --- Browser Tools ---


async def browser_navigate(url: str) -> str:
    """Navigate to URL and return page title."""
    logger.info(f"[TOOL] browser_navigate: {url}")
    page = await get_browser_manager().ensure_browser()
    try:
        await page.goto(url, wait_until="networkidle", timeout=600000)

        # Auto-dismiss common cookie/consent popups
        cookie_dismissers = [
            "button:has-text('AGREE AND PROCEED')",
            "button:has-text('Agree and proceed')",
            "button:has-text('Accept all')",
            "button:has-text('Accept All')",
            "button:has-text('Accept')",
            "button:has-text('I agree')",
            "button:has-text('I Agree')",
            "button:has-text('Got it')",
            "button:has-text('OK')",
            "button:has-text('Continue')",
            "button:has-text('Close')",
            "[aria-label='Close']",
            "[aria-label='close']",
            ".cookie-accept",
            "#accept-cookies",
            "#onetrust-accept-btn-handler",
            ".cc-accept",
        ]
        for _ in range(3):  # Try multiple times in case popups appear after delay
            for selector in cookie_dismissers:
                try:
                    if await page.locator(selector).count() > 0:
                        await page.locator(selector).first.click(timeout=2000)
                        logger.info(f"[NAV] Dismissed popup: {selector}")
                        await page.wait_for_timeout(500)
                        break
                except Exception:
                    pass
            await page.wait_for_timeout(300)

        return json.dumps({
            "status": "success",
            "url": page.url,
            "title": await page.title(),
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


async def browser_get_text() -> str:
    """Get visible text content from page."""
    page = await get_browser_manager().ensure_browser()
    try:
        # 10 minute timeout for getting page text (pages can be slow)
        text = await page.inner_text("body", timeout=600000)
        # Truncate for LLM context
        return text[:3000] if len(text) > 3000 else text
    except Exception as e:
        logger.error(f"[TOOL] browser_get_text ERROR: {e}")
        return json.dumps({"status": "error", "message": str(e)})


async def browser_click(selector: str) -> str:
    """Click element by CSS selector or text."""
    logger.info(f"[TOOL] browser_click: {selector}")
    page = await get_browser_manager().ensure_browser()
    try:
        # Try as CSS selector first with 10 minute timeout
        if await page.locator(selector).count() > 0:
            await page.locator(selector).first.click(timeout=600000)
        else:
            # Try as text content
            await page.get_by_text(selector, exact=False).first.click(timeout=600000)
        await page.wait_for_timeout(500)
        return json.dumps({"status": "clicked", "selector": selector})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


async def browser_get_elements() -> str:
    """List interactive elements on page."""
    import asyncio
    page = await get_browser_manager().ensure_browser()
    elements: list[dict[str, str]] = []

    try:
        # 10 minute overall timeout for element discovery
        async with asyncio.timeout(600):
            # Get buttons
            buttons = await page.locator("button").all()
            for btn in buttons[:10]:
                try:
                    text = await btn.inner_text(timeout=60000)
                    text = text[:50]
                    if text.strip():
                        elements.append({"type": "button", "text": text})
                except Exception:
                    pass

            # Get links
            links = await page.locator("a").all()
            for link in links[:10]:
                try:
                    text = await link.inner_text(timeout=60000)
                    text = text[:50]
                    if text.strip():
                        elements.append({"type": "link", "text": text})
                except Exception:
                    pass

            return json.dumps(elements[:15])
    except asyncio.TimeoutError:
        logger.error("[TOOL] browser_get_elements: timed out after 10 minutes")
        return json.dumps({"status": "error", "message": "Timed out getting elements"})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


async def browser_wait(seconds: int) -> str:
    """Wait for specified seconds. Limited to 5 minutes max."""
    # Cap at 5 minutes to prevent hanging
    if seconds > 300:
        logger.warning(f"[TOOL] browser_wait: capping {seconds}s to 300s max")
        seconds = 300
    page = await get_browser_manager().ensure_browser()
    await page.wait_for_timeout(seconds * 1000)
    return f"Waited {seconds} seconds"


async def browser_paste_code(code: str) -> str:
    """
    Paste code into the active editor.
    Uses clipboard paste as primary method (much faster than typing).
    Falls back to typing if paste fails.
    """
    import asyncio
    logger.info(f"[TOOL] browser_paste_code: {len(code)} chars")
    page = await get_browser_manager().ensure_browser()
    
    # Overall timeout: 10 minutes for pasting code
    try:
        async with asyncio.timeout(600):
            # First, try to find and focus the code editor
            editor_selectors = [
                "textarea",  # Plain textarea (most common)
                ".ace_text-input",  # ACE Editor input
                ".ace_editor",  # ACE Editor container
                ".monaco-editor textarea",  # Monaco Editor
                ".CodeMirror textarea",  # CodeMirror
                "[contenteditable=true]",  # Contenteditable div
                ".editor",  # Generic editor class
                "#code",  # Common ID
                "#source",  # Common ID
            ]

            focused = False
            for selector in editor_selectors:
                try:
                    if await page.locator(selector).count() > 0:
                        await page.locator(selector).first.click(timeout=60000)
                        focused = True
                        await page.wait_for_timeout(200)
                        break
                except Exception:
                    continue

            if not focused:
                # Click in the upper area of the page (usually where editors are)
                viewport = page.viewport_size
                if viewport:
                    await page.mouse.click(viewport["width"] // 2, viewport["height"] // 3)
                    await page.wait_for_timeout(200)

            # Select all existing content
            mod_key = "Meta" if sys.platform == "darwin" else "Control"
            await page.keyboard.press(f"{mod_key}+a")
            await page.wait_for_timeout(100)

            # Delete selected content
            await page.keyboard.press("Backspace")
            await page.wait_for_timeout(100)

            # Try clipboard paste first (much faster for large code)
            try:
                await page.evaluate(f"navigator.clipboard.writeText({json.dumps(code)})")
                await page.keyboard.press(f"{mod_key}+v")
                await page.wait_for_timeout(300)
                logger.info(f"[TOOL] browser_paste_code: pasted {len(code)} chars via clipboard")
                return json.dumps({"status": "success", "code_length": len(code), "method": "clipboard"})
            except Exception as paste_err:
                logger.warning(f"[TOOL] Clipboard paste failed, falling back to typing: {paste_err}")

            # Fallback: Type the code directly (slower but more reliable)
            await page.keyboard.type(code, delay=1)

            return json.dumps({"status": "success", "code_length": len(code), "method": "typing"})
    except asyncio.TimeoutError:
        logger.error("[TOOL] browser_paste_code: timed out after 10 minutes")
        return json.dumps({"status": "error", "message": "Operation timed out after 10 minutes"})
    except Exception as e:
        logger.error(f"[TOOL] browser_paste_code ERROR: {e}")
        return json.dumps({"status": "error", "message": str(e)})


async def browser_type_slow(text: str) -> str:
    """
    Type text character by character. Fallback for editors that don't support paste.
    """
    import asyncio
    page = await get_browser_manager().ensure_browser()
    try:
        # 10 minute overall timeout
        async with asyncio.timeout(600):
            # Select all first to replace
            mod_key = "Meta" if sys.platform == "darwin" else "Control"
            await page.keyboard.press(f"{mod_key}+a")
            await page.wait_for_timeout(100)

            # Type with delay between characters
            await page.keyboard.type(text, delay=10)

            return json.dumps({"status": "success", "chars_typed": len(text)})
    except asyncio.TimeoutError:
        logger.error("[TOOL] browser_type_slow: timed out after 10 minutes")
        return json.dumps({"status": "error", "message": "Typing timed out after 10 minutes"})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


async def browser_press_key(key: str) -> str:
    """Press a keyboard key (Enter, Tab, Escape, etc.)."""
    page = await get_browser_manager().ensure_browser()
    try:
        await page.keyboard.press(key)
        return json.dumps({"status": "pressed", "key": key})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


async def browser_analyze_page() -> str:
    """
    Analyze the current page to determine if it's ready for code input.
    Returns structured info about code editors, textareas, and run buttons.
    """
    import asyncio
    logger.info("[TOOL] browser_analyze_page")
    page = await get_browser_manager().ensure_browser()
    try:
        # 10 minute overall timeout for page analysis
        async with asyncio.timeout(600):
            # Check for code editors / textareas
            editor_found: dict[str, str] | None = None
            editor_checks = [
                ("textarea", "textarea"),
                (".ace_editor", "ACE editor"),
                (".CodeMirror", "CodeMirror"),
                (".monaco-editor", "Monaco editor"),
                ("#code", "code input"),
                ("#source", "source input"),
            ]

            for selector, name in editor_checks:
                try:
                    if await page.locator(selector).count() > 0:
                        editor_found = {"selector": selector, "type": name}
                        break
                except Exception:
                    pass

            # Check for run/execute buttons
            run_button_found: dict[str, str] | None = None
            run_checks = [
                ("button:has-text('Run')", "Run"),
                ("button:has-text('Execute')", "Execute"),
                ("button:has-text('Submit')", "Submit"),
                ("#run", "run"),
                (".run-button", "run-button"),
                ("button:has-text('Go')", "Go"),
                ("[data-testid='run']", "run testid"),
            ]

            for selector, name in run_checks:
                try:
                    if await page.locator(selector).count() > 0:
                        run_button_found = {"selector": selector, "name": name}
                        break
                except Exception:
                    pass

            ready = editor_found is not None and run_button_found is not None

            result: dict[str, Any] = {
                "ready_for_code": ready,
                "editor": editor_found,
                "run_button": run_button_found,
            }

            if ready and run_button_found:
                result["action"] = f"READY! Use browser_paste_code, then browser_click with selector: {run_button_found['selector']}"
            elif editor_found and not run_button_found:
                result["action"] = "Has editor but no Run button found. Try pressing Ctrl+Enter or look for other buttons."
            else:
                result["action"] = "NOT a playground. Go back and try a different URL."

            return json.dumps(result)
    except asyncio.TimeoutError:
        logger.error("[TOOL] browser_analyze_page: timed out after 10 minutes")
        return json.dumps({"status": "error", "message": "Page analysis timed out after 10 minutes"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Tool Registry for Daemon ---

# Export all async tool functions for registration
ASYNC_BROWSER_TOOLS: dict[str, Any] = {
    "web_search": web_search,
    "browser_navigate": browser_navigate,
    "browser_get_text": browser_get_text,
    "browser_click": browser_click,
    "browser_get_elements": browser_get_elements,
    "browser_wait": browser_wait,
    "browser_paste_code": browser_paste_code,
    "browser_type_slow": browser_type_slow,
    "browser_press_key": browser_press_key,
    "browser_analyze_page": browser_analyze_page,
}
