#!/usr/bin/env python3
"""
Demo: Qwen3 using browser tools to run Rust hello world.

This demonstrates the tool-calling LLM controlling a real browser.
"""

import json
import sys
from playwright.sync_api import sync_playwright

from llm import ToolCallingAgent, Tool


# --- Browser State (module-level for tool access) ---
_browser_context = {"browser": None, "page": None, "playwright": None}


def _ensure_browser():
    """Lazy-init browser."""
    if _browser_context["page"] is None:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=False)  # Visible browser!
        page = browser.new_page()
        _browser_context["playwright"] = pw
        _browser_context["browser"] = browser
        _browser_context["page"] = page
    return _browser_context["page"]


def cleanup_browser():
    """Clean up browser resources."""
    if _browser_context["browser"]:
        _browser_context["browser"].close()
    if _browser_context["playwright"]:
        _browser_context["playwright"].stop()


# --- Tool Implementations ---

def browser_navigate(url: str) -> str:
    """Navigate to URL and return page title."""
    page = _ensure_browser()
    page.goto(url, wait_until="networkidle")
    return json.dumps({
        "status": "success",
        "url": page.url,
        "title": page.title(),
    })


def browser_get_text() -> str:
    """Get visible text content from page."""
    page = _ensure_browser()
    # Get text from main content areas
    text = page.inner_text("body")
    # Truncate for LLM context
    return text[:2000] if len(text) > 2000 else text


def browser_click(selector: str) -> str:
    """Click element by CSS selector or text."""
    page = _ensure_browser()
    try:
        # Try as CSS selector first
        if page.locator(selector).count() > 0:
            page.locator(selector).first.click()
        else:
            # Try as text content
            page.get_by_text(selector).first.click()
        page.wait_for_timeout(1000)
        return json.dumps({"status": "clicked", "selector": selector})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def browser_type(selector: str, text: str) -> str:
    """Type text into an input field."""
    page = _ensure_browser()
    try:
        page.locator(selector).first.fill(text)
        return json.dumps({"status": "typed", "text": text})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def browser_get_elements() -> str:
    """List interactive elements on page."""
    page = _ensure_browser()
    elements = []

    # Get buttons
    for btn in page.locator("button").all()[:10]:
        try:
            elements.append({"type": "button", "text": btn.inner_text()[:50]})
        except:
            pass

    # Get links
    for link in page.locator("a").all()[:10]:
        try:
            elements.append({"type": "link", "text": link.inner_text()[:50]})
        except:
            pass

    # Get inputs
    for inp in page.locator("input, textarea").all()[:5]:
        try:
            elements.append({"type": "input", "placeholder": inp.get_attribute("placeholder") or ""})
        except:
            pass

    return json.dumps(elements[:15])


def browser_screenshot() -> str:
    """Take screenshot and describe what we see."""
    page = _ensure_browser()
    page.screenshot(path="/tmp/qwen_browser_screenshot.png")
    return "Screenshot saved to /tmp/qwen_browser_screenshot.png"


def browser_wait(seconds: int) -> str:
    """Wait for specified seconds."""
    page = _ensure_browser()
    page.wait_for_timeout(seconds * 1000)
    return f"Waited {seconds} seconds"


# --- Tool Definitions ---

BROWSER_TOOLS = [
    Tool(
        name="browser_navigate",
        description="Navigate browser to a URL. Returns page title and URL.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to navigate to"}
            },
            "required": ["url"],
        },
        function=browser_navigate,
    ),
    Tool(
        name="browser_get_text",
        description="Get visible text content from the current page.",
        parameters={"type": "object", "properties": {}},
        function=browser_get_text,
    ),
    Tool(
        name="browser_click",
        description="Click an element. Use CSS selector like 'button' or '#id' or text content like 'Run'.",
        parameters={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector or visible text of element to click"}
            },
            "required": ["selector"],
        },
        function=browser_click,
    ),
    Tool(
        name="browser_type",
        description="Type text into an input field.",
        parameters={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of input field"},
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["selector", "text"],
        },
        function=browser_type,
    ),
    Tool(
        name="browser_get_elements",
        description="List clickable elements (buttons, links, inputs) on the page.",
        parameters={"type": "object", "properties": {}},
        function=browser_get_elements,
    ),
    Tool(
        name="browser_wait",
        description="Wait for a number of seconds.",
        parameters={
            "type": "object",
            "properties": {
                "seconds": {"type": "integer", "description": "Seconds to wait"}
            },
            "required": ["seconds"],
        },
        function=browser_wait,
    ),
]


# --- Main Demo ---

def main():
    model_size = sys.argv[1] if len(sys.argv) > 1 else "small"  # Default to small for faster demo

    print(f"🤖 Starting Qwen Browser Agent (model: {model_size})")
    print("=" * 60)

    agent = ToolCallingAgent(
        tools=BROWSER_TOOLS,
        model_size=model_size,
        system_prompt="""You are a browser automation agent. You MUST use the provided tools to interact with websites. You cannot access websites directly - you must call browser_navigate, browser_click, etc.

IMPORTANT: Always use tools. Never pretend or assume - actually call the tools to perform actions.

Workflow:
1. Use browser_navigate to go to a URL
2. Use browser_get_elements or browser_get_text to see what's on the page
3. Use browser_click to click buttons/links
4. Use browser_wait if you need to wait for something
5. Report actual results from tool responses""",
        max_tool_rounds=10,
    )

    # The task
    task = """Use your browser tools to:
1. Navigate to https://play.rust-lang.org/
2. Click the "Run" button to execute the code
3. Wait 3 seconds for compilation
4. Get the page text and tell me what output appeared"""

    print(f"📝 Task: {task}")
    print("=" * 60)
    print()

    try:
        response = agent.run(task)
        print("\n" + "=" * 60)
        print("🎯 Final Response from Qwen:")
        print(response)
    finally:
        cleanup_browser()


if __name__ == "__main__":
    main()
