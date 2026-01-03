#!/usr/bin/env python3
"""
Code Runner Agent: Qwen finds an online evaluator, writes code, and runs it.

Protocol:
1. Take programming language as argument
2. Take optional program description (default: fizzbuzz)
3. Find online evaluator (from model memory or web search)
4. Implement the program
5. Run it
6. Keep browser open for user interaction
"""

import json
import sys
import logging
from typing import Any

from playwright.sync_api import sync_playwright

from llm import ToolCallingAgent, Tool

from ddgs import DDGS

# Setup logging - file AND console with immediate flush
LOG_FILE = "/tmp/code_runner.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__).info

# Force unbuffered output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)


# --- Browser State (module-level for tool access) ---
_browser_context: dict[str, Any] = {"browser": None, "page": None, "playwright": None}


def _ensure_browser():
    """Lazy-init browser."""
    if _browser_context["page"] is None:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=False)  # Visible browser
        page = browser.new_page()
        _browser_context["playwright"] = pw
        _browser_context["browser"] = browser
        _browser_context["page"] = page
    return _browser_context["page"]


# --- Web Search Tool ---

def web_search(query: str) -> str:
    """Search the web using DuckDuckGo and return top results."""
    log(f"[TOOL] web_search: {query}")
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        
        if not results:
            log("[TOOL] web_search: no results")
            return json.dumps({"status": "no_results", "query": query})
        
        formatted = [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")[:200]}
            for r in results
        ]
        log(f"[TOOL] web_search: found {len(formatted)} results")
        return json.dumps({"status": "success", "results": formatted})
    except Exception as e:
        log(f"[TOOL] web_search ERROR: {e}")
        return json.dumps({"status": "error", "message": str(e)})


# --- Browser Tools ---

def browser_navigate(url: str) -> str:
    """Navigate to URL and return page title."""
    log(f"[TOOL] browser_navigate: {url}")
    page = _ensure_browser()
    try:
        page.goto(url, wait_until="networkidle", timeout=20000)
        
        # Auto-dismiss common cookie/consent popups (try multiple times)
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
                    if page.locator(selector).count() > 0:
                        page.locator(selector).first.click(timeout=2000)
                        log(f"[NAV] Dismissed popup: {selector}")
                        page.wait_for_timeout(500)
                        break
                except:
                    pass
            page.wait_for_timeout(300)
        
        return json.dumps({
            "status": "success",
            "url": page.url,
            "title": page.title(),
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def browser_get_text() -> str:
    """Get visible text content from page."""
    page = _ensure_browser()
    text = page.inner_text("body")
    # Truncate for LLM context
    return text[:3000] if len(text) > 3000 else text


def browser_click(selector: str) -> str:
    """Click element by CSS selector or text."""
    log(f"[TOOL] browser_click: {selector}")
    page = _ensure_browser()
    try:
        # Try as CSS selector first with short timeout
        if page.locator(selector).count() > 0:
            page.locator(selector).first.click(timeout=5000)
        else:
            # Try as text content
            page.get_by_text(selector, exact=False).first.click(timeout=5000)
        page.wait_for_timeout(500)
        return json.dumps({"status": "clicked", "selector": selector})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def browser_get_elements() -> str:
    """List interactive elements on page."""
    page = _ensure_browser()
    elements = []

    # Get buttons
    for btn in page.locator("button").all()[:10]:
        try:
            text = btn.inner_text()[:50]
            if text.strip():
                elements.append({"type": "button", "text": text})
        except:
            pass

    # Get links
    for link in page.locator("a").all()[:10]:
        try:
            text = link.inner_text()[:50]
            if text.strip():
                elements.append({"type": "link", "text": text})
        except:
            pass

    return json.dumps(elements[:15])


def browser_wait(seconds: int) -> str:
    """Wait for specified seconds."""
    page = _ensure_browser()
    page.wait_for_timeout(seconds * 1000)
    return f"Waited {seconds} seconds"


def browser_paste_code(code: str) -> str:
    """
    Paste code into the active editor.
    Uses keyboard typing as primary method (most reliable).
    """
    log(f"[TOOL] browser_paste_code: {len(code)} chars")
    page = _ensure_browser()
    try:
        # First, try to find and focus the code editor
        editor_selectors = [
            "textarea",              # Plain textarea (most common)
            ".ace_text-input",       # ACE Editor input
            ".ace_editor",           # ACE Editor container
            ".monaco-editor textarea",  # Monaco Editor
            ".CodeMirror textarea",  # CodeMirror
            "[contenteditable=true]", # Contenteditable div
            ".editor",               # Generic editor class
            "#code",                 # Common ID
            "#source",               # Common ID
        ]
        
        focused = False
        for selector in editor_selectors:
            try:
                if page.locator(selector).count() > 0:
                    page.locator(selector).first.click()
                    focused = True
                    page.wait_for_timeout(200)
                    break
            except:
                continue
        
        if not focused:
            # Click in the upper area of the page (usually where editors are)
            page.mouse.click(page.viewport_size["width"] // 2, page.viewport_size["height"] // 3)
            page.wait_for_timeout(200)
        
        # Select all existing content
        mod_key = "Meta" if sys.platform == "darwin" else "Control"
        page.keyboard.press(f"{mod_key}+a")
        page.wait_for_timeout(100)
        
        # Delete selected content
        page.keyboard.press("Backspace")
        page.wait_for_timeout(100)
        
        # Type the code directly (most reliable method)
        # Use fast typing for shorter code, slower for longer
        delay = 2 if len(code) < 500 else 1
        page.keyboard.type(code, delay=delay)
        
        return json.dumps({"status": "success", "code_length": len(code)})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def browser_type_slow(text: str) -> str:
    """
    Type text character by character. Fallback for editors that don't support paste.
    """
    page = _ensure_browser()
    try:
        # Select all first to replace
        page.keyboard.press("Control+a" if sys.platform != "darwin" else "Meta+a")
        page.wait_for_timeout(100)
        
        # Type with delay between characters
        page.keyboard.type(text, delay=10)
        
        return json.dumps({"status": "success", "chars_typed": len(text)})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def browser_press_key(key: str) -> str:
    """Press a keyboard key (Enter, Tab, Escape, etc.)."""
    page = _ensure_browser()
    try:
        page.keyboard.press(key)
        return json.dumps({"status": "pressed", "key": key})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def browser_analyze_page() -> str:
    """
    Analyze the current page to determine if it's ready for code input.
    Returns structured info about code editors, textareas, and run buttons.
    """
    log("[TOOL] browser_analyze_page")
    page = _ensure_browser()
    try:
        # Check for code editors / textareas
        editor_found = None
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
                if page.locator(selector).count() > 0:
                    editor_found = {"selector": selector, "type": name}
                    break
            except:
                pass
        
        # Check for run/execute buttons
        run_button_found = None
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
                if page.locator(selector).count() > 0:
                    run_button_found = {"selector": selector, "name": name}
                    break
            except:
                pass
        
        ready = editor_found is not None and run_button_found is not None
        
        result = {
            "ready_for_code": ready,
            "editor": editor_found,
            "run_button": run_button_found,
        }
        
        if ready:
            result["action"] = f"READY! Use browser_paste_code, then browser_click with selector: {run_button_found['selector']}"
        elif editor_found and not run_button_found:
            result["action"] = "Has editor but no Run button found. Try pressing Ctrl+Enter or look for other buttons."
        else:
            result["action"] = "NOT a playground. Go back and try a different URL."
        
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Tool Definitions ---

ALL_TOOLS = [
    Tool(
        name="web_search",
        description="Search the web using DuckDuckGo. Use this to find online code playgrounds for unfamiliar languages.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query, e.g. 'Haskell online playground'"}
            },
            "required": ["query"],
        },
        function=web_search,
    ),
    Tool(
        name="browser_navigate",
        description="Navigate browser to a URL. Returns page title and final URL.",
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
        description="Get visible text content from the current page. Use to see output after running code.",
        parameters={"type": "object", "properties": {}},
        function=browser_get_text,
    ),
    Tool(
        name="browser_click",
        description="Click an element. Use CSS selector like 'button', '#run-btn' or visible text like 'Run'.",
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
        name="browser_get_elements",
        description="List clickable elements (buttons, links) on the page. Useful to find the Run button.",
        parameters={"type": "object", "properties": {}},
        function=browser_get_elements,
    ),
    Tool(
        name="browser_wait",
        description="Wait for a number of seconds. Use after clicking Run to wait for execution.",
        parameters={
            "type": "object",
            "properties": {
                "seconds": {"type": "integer", "description": "Seconds to wait (1-10)"}
            },
            "required": ["seconds"],
        },
        function=browser_wait,
    ),
    Tool(
        name="browser_paste_code",
        description="Paste code into the editor. Automatically finds the code editor, selects all, and pastes. Use this as the primary way to enter code.",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "The complete source code to paste"}
            },
            "required": ["code"],
        },
        function=browser_paste_code,
    ),
    Tool(
        name="browser_type_slow",
        description="Type text character by character. Use as fallback if browser_paste_code fails.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type slowly"}
            },
            "required": ["text"],
        },
        function=browser_type_slow,
    ),
    Tool(
        name="browser_press_key",
        description="Press a keyboard key like Enter, Tab, Escape, F5, etc.",
        parameters={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key to press (Enter, Tab, Escape, F5, etc.)"}
            },
            "required": ["key"],
        },
        function=browser_press_key,
    ),
    Tool(
        name="browser_analyze_page",
        description="Analyze the current page to check if it has a code editor and run button. Returns structured info about whether the page is READY for code input. ALWAYS call this after navigating to a new page!",
        parameters={"type": "object", "properties": {}},
        function=browser_analyze_page,
    ),
]


# --- System Prompt ---

SYSTEM_PROMPT = """You are a code runner agent. Your task is to run code in online playgrounds.

## Your Capabilities
- You can search the web to find online code playgrounds
- You can control a browser to navigate, click, and type
- You can write code in any programming language

## Finding Playgrounds
You do NOT have hardcoded playground URLs. You MUST use web_search to find an online interpreter for the requested language.
Search for: "[language] online interpreter run code"

## Workflow
1. web_search for "[language] online interpreter run code"
2. browser_navigate to best result (NOT documentation/GitHub)
3. browser_analyze_page to check readiness
4. If ready_for_code is TRUE:
   a. browser_paste_code with your complete code
   b. browser_click using EXACT selector from run_button_selectors (e.g. "button:has-text('Run')")
   c. browser_wait for 2 seconds
   d. browser_get_text to see output
5. If NOT ready: try another URL

CRITICAL: Use the EXACT selectors returned by browser_analyze_page! Do not guess.

## IMPORTANT WARNINGS
- A playground MUST have: (1) code input area, (2) Run/Execute button, (3) output area
- Documentation sites, wikis, and GitHub repos are NOT playgrounds!
- If the first site doesn't work, search again with different terms
- Write COMPLETE, working code - not pseudocode
- Always include necessary imports/includes
- Make sure the code is syntactically correct
- After running, tell the user what output you observed
- Do NOT close the browser - leave it open for the user"""


# --- Main Entry Point ---

def run_code_agent(language: str, program_description: str = "fizzbuzz", model_size: str = "small", timeout: int = 120):
    """
    Run the code agent to implement and execute a program.
    
    Args:
        language: Programming language (e.g., "python", "rust", "haskell")
        program_description: What the program should do (default: "fizzbuzz")
        model_size: LLM model size ("small", "medium", "large")
        timeout: Maximum time in seconds (default: 120)
    """
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Agent timed out after {timeout} seconds")
    
    # Set up timeout
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout)
    
    print(f"🤖 Code Runner Agent")
    print(f"   Language: {language}")
    print(f"   Program: {program_description}")
    print(f"   Model: {model_size}")
    print(f"   Timeout: {timeout}s")
    print("=" * 60)
    
    agent = ToolCallingAgent(
        tools=ALL_TOOLS,
        model_size=model_size,
        system_prompt=SYSTEM_PROMPT,
        max_tool_rounds=10,  # Reduced from 15
    )
    
    task = f"""Write and run a {language} program that implements: {program_description}

Steps:
1. Find or navigate to an online {language} playground
2. Write the complete {language} code for: {program_description}
3. Paste the code into the editor
4. Run it
5. Report the output

Remember to write COMPLETE, syntactically correct {language} code."""

    print(f"\n📝 Task:\n{task}")
    print("=" * 60 + "\n")
    
    try:
        response = agent.run(task, verbose=True)
        signal.alarm(0)  # Cancel timeout
        
        print("\n" + "=" * 60)
        print("🎯 Agent Response:")
        print(response)
        print("=" * 60)
        print("\n🌐 Browser is still open. You can interact with the results.")
        print("   Press Ctrl+C to exit when done.\n")
        
    except TimeoutError as e:
        signal.alarm(0)
        print(f"\n⏰ {e}")
        print("🌐 Browser is still open. You can interact manually.")
    
    # Keep the script running so browser stays open
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Closing browser...")
        if _browser_context["browser"]:
            _browser_context["browser"].close()
        if _browser_context["playwright"]:
            _browser_context["playwright"].stop()


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python code_runner_agent.py <language> [program_description] [model_size]")
        print()
        print("Examples:")
        print("  python code_runner_agent.py python")
        print("  python code_runner_agent.py rust 'hello world'")
        print("  python code_runner_agent.py haskell 'quicksort' medium")
        print()
        print("Languages: python, rust, go, javascript, haskell, ruby, java, c, cpp, typescript, etc.")
        print("Model sizes: small (7B), medium (14B), large (32B)")
        sys.exit(1)
    
    language = sys.argv[1]
    program_description = sys.argv[2] if len(sys.argv) > 2 else "fizzbuzz"
    model_size = sys.argv[3] if len(sys.argv) > 3 else "small"
    
    run_code_agent(language, program_description, model_size)


if __name__ == "__main__":
    main()
