# Tools

Tools are self-contained, locally-invokable functions that extend the LLM's capabilities.

## Overview

The tool system provides:

- **LLM-mediated invocation**: Tools called by the model during chat
- **Direct API invocation**: Tools called directly via HTTP without LLM
- **Lazy loading**: Tools loaded on first use for fast startup
- **Async support**: Both sync and async tool implementations

## Architecture

Each tool is a module that bundles:

1. **Spec**: JSON Schema describing the tool for the LLM
2. **Implementation**: Python function that executes the tool

```
┌─────────────────────────────────────────────────────────┐
│                      Tool Module                        │
├─────────────────────────────────────────────────────────┤
│  ToolSpec                    │  ToolFunction            │
│  ├─ name                     │  ├─ Sync or Async        │
│  ├─ description              │  ├─ Takes typed args     │
│  └─ parameters (JSON Schema) │  └─ Returns JSON string  │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  Tool Registry  │
                    │  (singleton)    │
                    └─────────────────┘
```

## Direct Tool Invocation

Call any tool directly via the API:

```bash
# Get current datetime
curl -X POST http://127.0.0.1:5997/v1/tools/get_current_datetime/invoke \
  -H "Content-Type: application/json" \
  -d '{"arguments": {}}'

# Search Linear issues
curl -X POST http://127.0.0.1:5997/v1/tools/search_linear_issues/invoke \
  -H "Content-Type: application/json" \
  -d '{"arguments": {"state": "In Progress", "limit": 5}}'

# Navigate browser
curl -X POST http://127.0.0.1:5997/v1/tools/browser_navigate/invoke \
  -H "Content-Type: application/json" \
  -d '{"arguments": {"url": "https://example.com"}}'
```

Response:

```json
{
  "tool_name": "get_current_datetime",
  "result": {
    "utc": {
      "iso": "2024-01-08T12:00:00+00:00",
      "date": "2024-01-08",
      "day_of_week": "Monday"
    },
    "local": {...},
    "hints": {...}
  },
  "latency_ms": 1.2
}
```

## Available Tools

### Mirror Tools

Data access for Linear and Slack mirrors.

| Tool | Description |
|------|-------------|
| `get_current_datetime` | Get current time with date range hints |
| `search_linear_issues` | Search issues by keyword, state, assignee |
| `get_linear_issue` | Get full issue details by identifier |
| `list_linear_events` | List recent activity events |
| `search_slack_messages` | Search Slack messages |
| `get_slack_thread` | Get full thread with replies |
| `list_recent_slack_activity` | Browse recent conversations |
| `lookup_user` | Find user by name or ID |
| `run_python` | Execute Python code with data science libs |

### Browser Tools

Playwright-based browser automation.

| Tool | Description |
|------|-------------|
| `web_search` | Search the web via DuckDuckGo |
| `browser_navigate` | Navigate to a URL |
| `browser_get_text` | Extract page text content |
| `browser_click` | Click an element |
| `browser_get_elements` | Query elements by selector |
| `browser_wait` | Wait for element or timeout |
| `browser_paste_code` | Paste code into editor |
| `browser_type_slow` | Type text character by character |
| `browser_press_key` | Press keyboard key |
| `browser_analyze_page` | Analyze page structure |

### OCR Tools

Document text extraction using vision-language models on Apple Silicon.

| Tool | Description |
|------|-------------|
| `ocr_document` | Extract text from images or PDFs using Qwen2.5-VL-7B |

**Supported formats:**
- Images: PNG, JPG, JPEG, WEBP, GIF, BMP, TIFF
- Documents: PDF (multi-page support)

**Example usage:**

```bash
# OCR an image
curl -X POST http://127.0.0.1:5997/v1/tools/ocr_document/invoke \
  -H "Content-Type: application/json" \
  -d '{"arguments": {"file_path": "/path/to/document.png"}}'

# OCR specific pages of a PDF
curl -X POST http://127.0.0.1:5997/v1/tools/ocr_document/invoke \
  -H "Content-Type: application/json" \
  -d '{"arguments": {"file_path": "/path/to/document.pdf", "pages": "1-3", "dpi": 300}}'
```

**Model:** Uses `mlx-community/Qwen2.5-VL-7B-Instruct-8bit` - a 7B parameter vision-language model optimized for Apple Silicon. The model is loaded lazily on first use.

**Requirements:** `mlx-vlm` and `pymupdf` (installed via requirements.txt)

## Creating Custom Tools

### Using the @tool Decorator

The simplest way to create a tool:

```python
import json
from daemon.tools.base import tool

@tool(
    name="get_weather",
    description="Get current weather for a city",
    parameters={
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name"
            },
            "units": {
                "type": "string",
                "enum": ["celsius", "fahrenheit"],
                "description": "Temperature units"
            }
        },
        "required": ["city"]
    }
)
def get_weather(city: str, units: str = "celsius") -> str:
    """Fetch weather data for a city."""
    # Your implementation here
    data = fetch_weather_api(city, units)
    return json.dumps({
        "city": city,
        "temperature": data["temp"],
        "units": units,
        "conditions": data["conditions"]
    })

# Export as TOOL for the registry
TOOL = get_weather
```

### Async Tools

For I/O-bound operations, use async:

```python
@tool(
    name="fetch_url",
    description="Fetch content from a URL",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"}
        },
        "required": ["url"]
    }
)
async def fetch_url(url: str) -> str:
    """Fetch URL content asynchronously."""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            content = await response.text()
            return json.dumps({
                "status": response.status,
                "content_length": len(content),
                "content": content[:1000]  # Truncate for LLM
            })

TOOL = fetch_url
```

### Manual Tool Definition

For more control, create Tool and ToolSpec directly:

```python
from daemon.tools.base import Tool, ToolSpec

spec = ToolSpec(
    name="calculate",
    description="Perform mathematical calculations",
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Math expression to evaluate"
            }
        },
        "required": ["expression"]
    }
)

def calculate(expression: str) -> str:
    try:
        # Safe evaluation (use ast.literal_eval in production)
        result = eval(expression)
        return json.dumps({"expression": expression, "result": result})
    except Exception as e:
        return json.dumps({"error": str(e)})

TOOL = Tool(spec=spec, execute=calculate)
```

## Registering Tools

### Lazy Registration (Recommended)

Add your tool to the registry in `daemon/tools/registry.py`:

```python
def _populate_registry(registry: ToolRegistry) -> None:
    # ... existing tools ...

    # Your custom tools
    registry.register_lazy("get_weather", "daemon.tools.custom.get_weather", "TOOL")
```

This defers module import until the tool is first used.

### Direct Registration

For tools that should load immediately:

```python
from daemon.tools import get_registry
from .my_tool import TOOL as my_tool

registry = get_registry()
registry.register(my_tool)
```

## Tool Execution Flow

### LLM-Mediated Flow

```
User Message
     │
     ▼
┌─────────────┐
│ Build Prompt│◄── System prompt + tool schemas
└─────────────┘
     │
     ▼
┌─────────────┐
│   LLM       │
│ Inference   │
└─────────────┘
     │
     ▼ (if tool calls in response)
┌─────────────┐
│ Parse Tool  │◄── Extract <tool_call> XML
│   Calls     │
└─────────────┘
     │
     ▼
┌─────────────┐
│  Execute    │◄── Registry.execute_async()
│   Tools     │
└─────────────┘
     │
     ▼
┌─────────────┐
│ Format      │◄── Inject results as <tool_response>
│ Results     │
└─────────────┘
     │
     ▼
┌─────────────┐
│   LLM       │◄── Continue generation with results
│ (next round)│
└─────────────┘
```

### Tool Call Format (LLM Output)

The LLM emits tool calls in XML format:

```xml
<tool_call>
{"name": "search_linear_issues", "arguments": {"state": "In Progress"}}
</tool_call>
```

### Tool Response Format (Injected)

Results are injected as user messages:

```xml
<tool_response>
{"name": "search_linear_issues", "result": "{\"total\": 5, ...}"}
</tool_response>
```

## Best Practices

### Return JSON Strings

Tools must return JSON-encoded strings for LLM consumption:

```python
# Good
return json.dumps({"status": "success", "data": result})

# Bad - will cause issues
return {"status": "success", "data": result}
```

### Handle Errors Gracefully

Return error information in JSON, don't raise exceptions:

```python
def my_tool(arg: str) -> str:
    try:
        result = risky_operation(arg)
        return json.dumps({"result": result})
    except SpecificError as e:
        return json.dumps({"error": f"Operation failed: {e}"})
```

### Truncate Large Results

LLM context is limited. Truncate or summarize large outputs:

```python
def search_tool(query: str) -> str:
    results = fetch_many_results(query)
    # Return summary, not all data
    return json.dumps({
        "total": len(results),
        "top_results": results[:10],
        "has_more": len(results) > 10
    })
```

### Provide Helpful Descriptions

Tool descriptions guide the LLM on when and how to use tools:

```python
@tool(
    name="get_current_datetime",
    description="Get the current date and time. ALWAYS call this first "
                "when answering questions about time periods like "
                "'last week', 'this month', 'recently', etc.",
    parameters={...}
)
```

### Use Type Hints

Type hints improve code clarity and enable IDE support:

```python
async def browser_navigate(url: str) -> str:
    """Navigate browser to URL."""
    ...
```
