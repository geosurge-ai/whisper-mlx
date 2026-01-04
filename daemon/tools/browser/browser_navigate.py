"""
Browser navigate tool.

Navigate to a URL and handle cookie consent popups.
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
    name="browser_navigate",
    description="Navigate browser to a URL. Returns page title and final URL.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to navigate to"},
        },
        "required": ["url"],
    },
)
async def browser_navigate(url: str) -> str:
    """Navigate to URL and return page title."""
    logger.info(f"[TOOL] browser_navigate: {url}")
    page = await get_browser_manager().ensure_browser()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_load_state("load", timeout=30000)

        # Inject CSS to hide cookie popups
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

        # Try to click dismiss buttons
        cookie_button = (
            page.get_by_role("button", name="Accept all")
            .or_(page.get_by_role("button", name="Accept All"))
            .or_(page.get_by_role("button", name="Accept"))
            .or_(page.get_by_role("button", name="Accept Cookies"))
            .or_(page.get_by_role("button", name="I agree"))
            .or_(page.get_by_role("button", name="Agree"))
            .or_(page.get_by_role("button", name="Allow all"))
            .or_(page.get_by_role("button", name="Continue"))
            .or_(page.get_by_role("button", name="OK"))
            .or_(page.get_by_role("button", name="Got it"))
            .or_(page.locator("#onetrust-accept-btn-handler"))
            .or_(page.locator("#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"))
            .or_(page.locator(".cc-accept"))
        )
        try:
            await cookie_button.first.click(timeout=2000)
            logger.info("[NAV] Dismissed cookie popup via click")
            await page.wait_for_load_state("domcontentloaded", timeout=3000)
        except PlaywrightTimeout:
            pass

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


TOOL = browser_navigate
