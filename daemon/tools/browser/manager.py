"""
Shared browser manager for browser tools.

Provides a singleton browser instance that all browser tools share.
Uses Playwright's async API.
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

logger = logging.getLogger("qwen.browser")


class BrowserManager:
    """
    Manages a single shared browser instance.
    
    Lazy initialization - browser is created on first tool use.
    Uses a context with clipboard permissions for paste operations.
    """

    _instance: BrowserManager | None = None
    
    # Common consent management platform domains to block
    CMP_BLOCK_PATTERNS: list[str] = [
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
        """Block common consent management platform scripts."""
        async def block_handler(route) -> None:
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
            self._context = await self._browser.new_context(
                permissions=["clipboard-read", "clipboard-write"],
                service_workers="block",
            )
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
