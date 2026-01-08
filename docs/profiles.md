# Profiles

Profiles are pre-configured agent personas that bundle system prompts, tools, and inference settings.

## Overview

A profile defines:

- **System Prompt**: Instructions and persona for the LLM
- **Tools**: Curated set of tools available to the agent
- **Settings**: Max rounds, token limits, temperature

Profiles are immutable configurations - select one when creating a session or sending a chat message.

## Available Profiles

### mirror

Knowledge assistant for team data exploration.

**Use Case**: Query Linear issues, search Slack conversations, run data analysis.

**Tools**:
- `get_current_datetime`
- `run_python`
- `search_linear_issues`
- `get_linear_issue`
- `list_linear_events`
- `search_slack_messages`
- `get_slack_thread`
- `list_recent_slack_activity`
- `lookup_user`

**Settings**:
- Max Tool Rounds: 8
- Max Tokens: 4096

**System Prompt Excerpt**:
> You are a knowledge assistant with access to your team's Linear issues and Slack conversations, plus Python for data analysis.

### code_runner

Browser automation agent for running code in online playgrounds.

**Use Case**: Execute code snippets in web-based IDEs, interact with web applications.

**Tools**:
- `web_search`
- `browser_navigate`
- `browser_get_text`
- `browser_click`
- `browser_get_elements`
- `browser_wait`
- `browser_paste_code`
- `browser_type_slow`
- `browser_press_key`
- `browser_analyze_page`

**Settings**:
- Max Tool Rounds: 8
- Max Tokens: 4096

### general

Basic conversational assistant without tools.

**Use Case**: General Q&A, explanations, writing tasks.

**Tools**: None

**Settings**:
- Max Tool Rounds: 8
- Max Tokens: 4096

## Profile Structure

Profiles are defined in `daemon/profiles/` as Python modules:

```python
from .base import Profile
from daemon.tools.mirror import (
    get_current_datetime,
    search_linear_issues,
    # ... more tools
)

SYSTEM_PROMPT = """You are a knowledge assistant..."""

TOOLS = (
    get_current_datetime,
    search_linear_issues,
    # ... more tools
)

PROFILE = Profile(
    name="mirror",
    system_prompt=SYSTEM_PROMPT,
    tools=TOOLS,
    max_tool_rounds=8,
    max_tokens=4096,
)
```

## Profile API

### List Profiles

```bash
curl http://127.0.0.1:5997/v1/profiles
```

```json
[
  {
    "name": "mirror",
    "system_prompt_preview": "You are a knowledge assistant with access to...",
    "tool_names": ["get_current_datetime", "search_linear_issues", ...],
    "max_tool_rounds": 8
  },
  {
    "name": "code_runner",
    "system_prompt_preview": "You are a code execution assistant...",
    "tool_names": ["browser_navigate", "browser_click", ...],
    "max_tool_rounds": 8
  },
  {
    "name": "general",
    "system_prompt_preview": "You are a helpful assistant...",
    "tool_names": [],
    "max_tool_rounds": 8
  }
]
```

### Get Profile Tools

```bash
curl http://127.0.0.1:5997/v1/profiles/mirror/tools
```

Returns full tool specifications for tools in the profile.

## Creating Custom Profiles

### 1. Create Profile Module

Create a new file in `daemon/profiles/`:

```python
# daemon/profiles/researcher.py

from .base import Profile
from daemon.tools.mirror import (
    get_current_datetime,
    search_linear_issues,
    get_linear_issue,
)
from daemon.tools.browser import (
    web_search,
    browser_navigate,
    browser_get_text,
)

SYSTEM_PROMPT = """You are a research assistant that helps investigate topics.

## Your Capabilities

1. **Web Search**: Find information on the internet
2. **Linear**: Access project management data
3. **Time Awareness**: Know the current date for time-sensitive queries

## How to Work

1. Start with web_search to find relevant sources
2. Use browser tools to explore promising links
3. Cross-reference with Linear for internal context
4. Synthesize findings into clear summaries

Be thorough but concise. Cite sources when possible."""

TOOLS = (
    get_current_datetime,
    web_search,
    browser_navigate,
    browser_get_text,
    search_linear_issues,
    get_linear_issue,
)

PROFILE = Profile(
    name="researcher",
    system_prompt=SYSTEM_PROMPT,
    tools=TOOLS,
    max_tool_rounds=10,  # More rounds for complex research
    max_tokens=4096,
)
```

### 2. Register Profile

Add to `daemon/profiles/__init__.py`:

```python
from .researcher import PROFILE as researcher

ALL_PROFILES: dict[str, Profile] = {
    "mirror": mirror,
    "code_runner": code_runner,
    "general": general,
    "researcher": researcher,  # Add new profile
}
```

### 3. Use the Profile

```bash
curl -X POST http://127.0.0.1:5997/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"profile_name": "researcher"}'
```

## Profile Settings

### max_tool_rounds

Maximum inference rounds before stopping. Each round:

1. Model generates response
2. Tool calls extracted and executed
3. Results injected into context
4. Model continues (if more tool calls)

Default: 8 rounds

Higher values allow more complex multi-step workflows but increase latency and token usage.

### max_tokens

Maximum tokens per generation. Controls response length and cost.

Default: 4096 tokens

### temperature

Sampling temperature for generation (0.0 = deterministic, 1.0 = creative).

Default: 0.7

Not currently exposed via API, but can be set in profile definition.

## System Prompt Design

### Structure

Effective system prompts typically include:

1. **Role Definition**: Who the agent is
2. **Capabilities**: What tools/data are available
3. **Instructions**: How to approach tasks
4. **Constraints**: Limitations and boundaries
5. **Style Guide**: Response formatting preferences

### Example Pattern

```
You are a [ROLE] with access to [CAPABILITIES].

## Your Data Sources

1. **[Source 1]**: Description of what it contains
2. **[Source 2]**: Description of what it contains

## How to Answer Questions

1. [Step 1]
2. [Step 2]
3. [Step 3]

## Tool Strategy

- For [situation] → use [tool]
- For [situation] → use [tool]

## Response Style

- [Guideline 1]
- [Guideline 2]
```

### Tool Injection

The system prompt is automatically extended with tool schemas:

```
[Your system prompt]

# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{"name": "get_current_datetime", "description": "...", "parameters": {...}}
{"name": "search_linear_issues", "description": "...", "parameters": {...}}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{"name": "<function-name>", "arguments": {"<arg1>": "<value1>"}}
</tool_call>
```

## Best Practices

### Tool Curation

Only include tools the agent genuinely needs. Too many tools:

- Confuse the model about which to use
- Bloat the system prompt
- Increase likelihood of incorrect tool selection

### Clear Instructions

Be explicit about when to use tools:

```
## Tool Strategy

- For time-based questions → get_current_datetime FIRST, then other tools
- For project status → search_linear_issues + get_linear_issue
- For people questions → lookup_user
```

### Error Guidance

Help the agent handle tool failures:

```
If a tool returns an error, explain what you tried and suggest alternatives.
Don't repeat failed tool calls with the same arguments.
```

### Pagination Awareness

For tools with paginated results:

```
Results are paginated. Start with page 0 and reasonable limits.
Only fetch more pages if the user needs additional results.
```
