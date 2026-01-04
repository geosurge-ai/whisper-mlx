"""
Async browser tools for the Code_runner profile.

Uses Playwright's async API to avoid conflicts with FastAPI's asyncio event loop.
Provides a shared browser instance (visible, non-headless) for all sessions.

Best practices followed:
- Use domcontentloaded instead of networkidle (avoids hanging on WebSocket pages)
- Use semantic locators (get_by_role, get_by_text) over CSS selectors
- Avoid count() checks before actions (race condition)
- Use condition-based waits instead of hard-coded timeouts
- Catch specific Playwright exceptions, not bare Exception
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
    Error as PlaywrightError,
)

from ddgs import DDGS

logger = logging.getLogger("qwen.browser")


# --- Browser Manager (Singleton) ---


class BrowserManager:
    """
    Manages a single shared browser instance.
    
    Lazy initialization - browser is created on first tool use.
    All sessions share the same browser context for simplicity.
    Uses a context with clipboard permissions for paste operations.
    
    Cookie consent popups are handled by:
    1. Blocking common consent management platform (CMP) scripts via route interception
    2. Blocking service workers that might bypass route blocking
    3. Fallback button clicking for any popups that slip through
    """

    _instance: BrowserManager | None = None
    
    # Common consent management platform domains/patterns to block
    CMP_BLOCK_PATTERNS: list[str] = [
        # Major CMPs
        "**/cdn.cookielaw.org/**",
        "**/cookielaw.org/**",
        "**/onetrust.com/**",
        "**/consent.cookiebot.com/**",
        "**/cookiebot.com/**",
        "**/consent.trustarc.com/**",
        "**/trustarc.com/**",
        "**/quantcast.com/choice/**",
        "**/cdn-cookieyes.com/**",
        "**/cookieyes.com/**",
        "**/cmp.osano.com/**",
        "**/osano.com/**",
        "**/privacy-mgmt.com/**",
        "**/sp-prod.net/**",
        "**/sourcepoint.com/**",
        # Generic patterns
        "**/*cookie*consent*.js",
        "**/*cookie*banner*.js",
        "**/*cookie*notice*.js",
        "**/*gdpr*.js",
        "**/*cookie-law*.js",
        "**/*cookieconsent*.js",
    ]

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @classmethod
    def get_instance(cls) -> BrowserManager:
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def _setup_route_blocking(self, context: BrowserContext) -> None:
        """Block common consent management platform scripts via route interception."""
        blocked_count = 0
        
        async def block_handler(route) -> None:
            nonlocal blocked_count
            blocked_count += 1
            logger.debug(f"[BLOCK] Blocked CMP script: {route.request.url[:80]}...")
            await route.abort()
        
        for pattern in self.CMP_BLOCK_PATTERNS:
            await context.route(pattern, block_handler)
        
        logger.info(f"🛡️ Set up blocking for {len(self.CMP_BLOCK_PATTERNS)} CMP patterns")

    async def ensure_browser(self) -> Page:
        """Ensure browser is running and return the page."""
        if self._page is None:
            logger.info("🌐 Launching browser (visible mode)...")
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=False)
            # Create context with:
            # - Clipboard permissions for paste operations
            # - Service workers blocked (they can bypass route interception)
            self._context = await self._browser.new_context(
                permissions=["clipboard-read", "clipboard-write"],
                service_workers="block",
            )
            # Set up route blocking for consent management platforms
            await self._setup_route_blocking(self._context)
            self._page = await self._context.new_page()
            logger.info("✅ Browser ready (with CMP blocking)")
        return self._page

    async def close(self) -> None:
        """Close browser and cleanup resources."""
        if self._context is not None:
            await self._context.close()
            self._context = None
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
        # Use domcontentloaded - networkidle can hang on pages with WebSockets/polling
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # Wait for page to be fully loaded (but don't require network silence)
        await page.wait_for_load_state("load", timeout=30000)

        # Layer 1: Inject CSS to hide common cookie popup containers
        # This runs immediately and catches most popups before they fully render
        await page.add_style_tag(content="""
            [class*="cookie-banner"], [class*="cookie-consent"], [class*="cookie-notice"],
            [class*="cookiebanner"], [class*="cookieconsent"], [class*="cookienotice"],
            [id*="cookie-banner"], [id*="cookie-consent"], [id*="cookie-notice"],
            [id*="cookiebanner"], [id*="cookieconsent"], [id*="cookienotice"],
            [class*="gdpr"], [id*="gdpr"],
            [class*="consent-banner"], [id*="consent-banner"],
            [class*="privacy-banner"], [id*="privacy-banner"],
            .cc-window, .cc-banner, #CybotCookiebotDialog,
            #onetrust-consent-sdk, .onetrust-pc-dark-filter,
            [aria-label*="cookie" i], [aria-label*="consent" i] {
                display: none !important;
                visibility: hidden !important;
                opacity: 0 !important;
                pointer-events: none !important;
            }
        """)
        logger.debug("[NAV] Injected CSS to hide cookie popups")

        # Layer 2: Try to click dismiss buttons for any popups that slip through
        # Expanded list of button patterns
        cookie_button = (
            # Common accept patterns
            page.get_by_role("button", name="Accept all")
            .or_(page.get_by_role("button", name="Accept All"))
            .or_(page.get_by_role("button", name="Accept"))
            .or_(page.get_by_role("button", name="Accept Cookies"))
            .or_(page.get_by_role("button", name="Accept cookies"))
            # Agree patterns
            .or_(page.get_by_role("button", name="I agree"))
            .or_(page.get_by_role("button", name="Agree"))
            .or_(page.get_by_role("button", name="AGREE AND PROCEED"))
            .or_(page.get_by_role("button", name="Agree and proceed"))
            # Allow patterns
            .or_(page.get_by_role("button", name="Allow all"))
            .or_(page.get_by_role("button", name="Allow All"))
            .or_(page.get_by_role("button", name="Allow cookies"))
            .or_(page.get_by_role("button", name="Allow Cookies"))
            # Continue/OK patterns
            .or_(page.get_by_role("button", name="Continue"))
            .or_(page.get_by_role("button", name="Continue with Recommended Cookies"))
            .or_(page.get_by_role("button", name="OK"))
            .or_(page.get_by_role("button", name="Got it"))
            .or_(page.get_by_role("button", name="Got It"))
            # Consent patterns
            .or_(page.get_by_role("button", name="Consent"))
            .or_(page.get_by_role("button", name="I consent"))
            # Close patterns
            .or_(page.get_by_role("button", name="Close"))
            .or_(page.get_by_role("button", name="Dismiss"))
            # Common CMP-specific selectors
            .or_(page.locator("#onetrust-accept-btn-handler"))
            .or_(page.locator("#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"))
            .or_(page.locator(".cc-accept"))
            .or_(page.locator(".cc-btn.cc-dismiss"))
            .or_(page.locator("#accept-cookies"))
            .or_(page.locator("[data-cookiebanner='accept_button']"))
            # Generic fallback - any button in a cookie-related container
            .or_(page.locator("[class*='cookie'] button[class*='accept']"))
            .or_(page.locator("[class*='consent'] button[class*='accept']"))
        )
        try:
            # Short timeout - if no popup, move on quickly
            await cookie_button.first.click(timeout=2000)
            logger.info("[NAV] Dismissed cookie popup via click")
            # Wait for popup to close
            await page.wait_for_load_state("domcontentloaded", timeout=3000)
        except PlaywrightTimeout:
            pass  # No clickable cookie popup found, CSS hiding should have handled it

        return json.dumps({
            "status": "success",
            "url": page.url,
            "title": await page.title(),
        })
    except PlaywrightTimeout as e:
        logger.error(f"[TOOL] browser_navigate timeout: {e}")
        return json.dumps({"status": "error", "message": f"Navigation timed out: {e}"})
    except PlaywrightError as e:
        logger.error(f"[TOOL] browser_navigate error: {e}")
        return json.dumps({"status": "error", "message": str(e)})


async def browser_get_text() -> str:
    """Get visible text content from page."""
    page = await get_browser_manager().ensure_browser()
    try:
        # Wait for body to be present, then get text
        body = page.locator("body")
        await body.wait_for(state="attached", timeout=30000)
        text = await body.inner_text(timeout=30000)
        # Truncate for LLM context
        return text[:3000] if len(text) > 3000 else text
    except PlaywrightTimeout:
        logger.error("[TOOL] browser_get_text: timeout waiting for page content")
        return json.dumps({"status": "error", "message": "Timeout getting page text"})
    except PlaywrightError as e:
        logger.error(f"[TOOL] browser_get_text error: {e}")
        return json.dumps({"status": "error", "message": str(e)})


async def browser_click(selector: str) -> str:
    """
    Click element by selector or text.
    
    Tries multiple strategies in order:
    1. Role-based (if selector looks like a button/link name)
    2. Text-based 
    3. CSS selector
    """
    logger.info(f"[TOOL] browser_click: {selector}")
    page = await get_browser_manager().ensure_browser()
    
    try:
        # Build a combined locator that tries multiple strategies
        # Playwright will use the first one that matches
        locator = (
            page.get_by_role("button", name=selector)
            .or_(page.get_by_role("link", name=selector))
            .or_(page.get_by_text(selector, exact=False))
            .or_(page.locator(selector))
        )
        
        # Let Playwright's auto-waiting handle element presence
        # No need to check count() first - that's a race condition
        await locator.first.click(timeout=30000)
        
        # Wait for any navigation or state change triggered by click
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
        
        return json.dumps({"status": "clicked", "selector": selector})
    except PlaywrightTimeout:
        logger.warning(f"[TOOL] browser_click: element not found: {selector}")
        return json.dumps({"status": "error", "message": f"Element not found: {selector}"})
    except PlaywrightError as e:
        logger.error(f"[TOOL] browser_click error: {e}")
        return json.dumps({"status": "error", "message": str(e)})


async def browser_get_elements() -> str:
    """List interactive elements on page."""
    page = await get_browser_manager().ensure_browser()
    elements: list[dict[str, str]] = []

    try:
        # Use get_by_role for semantic element discovery
        # Get buttons using role
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

        # Get links using role
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
    
    Strategy (in order of preference):
    1. Use page.fill() for textareas (fastest, most reliable)
    2. Use keyboard paste via clipboard API
    3. Fall back to typing (slowest but works everywhere)
    """
    logger.info(f"[TOOL] browser_paste_code: {len(code)} chars")
    page = await get_browser_manager().ensure_browser()
    
    try:
        # Strategy 1: Try to find a fillable textarea and use page.fill()
        # This is the most reliable method for standard textareas
        textarea = page.locator("textarea").first
        try:
            await textarea.wait_for(state="visible", timeout=5000)
            await textarea.fill(code, timeout=30000)
            logger.info(f"[TOOL] browser_paste_code: filled {len(code)} chars via fill()")
            return json.dumps({"status": "success", "code_length": len(code), "method": "fill"})
        except PlaywrightTimeout:
            logger.debug("[TOOL] No fillable textarea found, trying other editors")

        # Strategy 2: Try specialized code editors (ACE, Monaco, CodeMirror)
        editor_locator = (
            page.locator(".ace_text-input")
            .or_(page.locator(".monaco-editor textarea"))
            .or_(page.locator(".CodeMirror textarea"))
            .or_(page.locator("[contenteditable=true]"))
        )
        
        try:
            await editor_locator.first.click(timeout=10000)
        except PlaywrightTimeout:
            # Last resort: click in center of page
            viewport = page.viewport_size
            if viewport:
                await page.mouse.click(viewport["width"] // 2, viewport["height"] // 3)

        # Select all and delete existing content
        mod_key = "Meta" if sys.platform == "darwin" else "Control"
        await page.keyboard.press(f"{mod_key}+a")
        await page.keyboard.press("Backspace")

        # Strategy 3: Try clipboard paste (context has clipboard permissions)
        try:
            await page.evaluate("text => navigator.clipboard.writeText(text)", code)
            await page.keyboard.press(f"{mod_key}+v")
            logger.info(f"[TOOL] browser_paste_code: pasted {len(code)} chars via clipboard")
            return json.dumps({"status": "success", "code_length": len(code), "method": "clipboard"})
        except PlaywrightError as paste_err:
            logger.warning(f"[TOOL] Clipboard paste failed: {paste_err}")

        # Strategy 4: Fall back to typing (slowest but works everywhere)
        await page.keyboard.type(code, delay=1)
        logger.info(f"[TOOL] browser_paste_code: typed {len(code)} chars")
        return json.dumps({"status": "success", "code_length": len(code), "method": "typing"})

    except PlaywrightTimeout as e:
        logger.error(f"[TOOL] browser_paste_code timeout: {e}")
        return json.dumps({"status": "error", "message": "Operation timed out"})
    except PlaywrightError as e:
        logger.error(f"[TOOL] browser_paste_code error: {e}")
        return json.dumps({"status": "error", "message": str(e)})


async def browser_type_slow(text: str) -> str:
    """
    Type text character by character. Fallback for editors that don't support paste.
    """
    logger.info(f"[TOOL] browser_type_slow: {len(text)} chars")
    page = await get_browser_manager().ensure_browser()
    try:
        # Select all first to replace existing content
        mod_key = "Meta" if sys.platform == "darwin" else "Control"
        await page.keyboard.press(f"{mod_key}+a")

        # Type with delay between characters (10ms = readable typing speed)
        await page.keyboard.type(text, delay=10)

        return json.dumps({"status": "success", "chars_typed": len(text)})
    except PlaywrightError as e:
        logger.error(f"[TOOL] browser_type_slow error: {e}")
        return json.dumps({"status": "error", "message": str(e)})


async def browser_press_key(key: str) -> str:
    """Press a keyboard key (Enter, Tab, Escape, etc.)."""
    logger.info(f"[TOOL] browser_press_key: {key}")
    page = await get_browser_manager().ensure_browser()
    try:
        await page.keyboard.press(key)
        return json.dumps({"status": "pressed", "key": key})
    except PlaywrightError as e:
        logger.error(f"[TOOL] browser_press_key error: {e}")
        return json.dumps({"status": "error", "message": str(e)})


async def browser_analyze_page() -> str:
    """
    Analyze the current page to determine if it's ready for code input.
    Returns structured info about code editors, textareas, and run buttons.
    """
    logger.info("[TOOL] browser_analyze_page")
    page = await get_browser_manager().ensure_browser()
    
    try:
        # Check for code editors / textareas using combined locator
        editor_locator = (
            page.locator("textarea")
            .or_(page.locator(".ace_editor"))
            .or_(page.locator(".CodeMirror"))
            .or_(page.locator(".monaco-editor"))
        )
        
        editor_found: dict[str, str] | None = None
        editor_count = await editor_locator.count()
        if editor_count > 0:
            # Determine which type was found
            if await page.locator("textarea").count() > 0:
                editor_found = {"selector": "textarea", "type": "textarea"}
            elif await page.locator(".ace_editor").count() > 0:
                editor_found = {"selector": ".ace_editor", "type": "ACE editor"}
            elif await page.locator(".CodeMirror").count() > 0:
                editor_found = {"selector": ".CodeMirror", "type": "CodeMirror"}
            elif await page.locator(".monaco-editor").count() > 0:
                editor_found = {"selector": ".monaco-editor", "type": "Monaco editor"}

        # Check for run/execute buttons using semantic locators
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
            # Determine which button was found
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
