# API Reference

Complete HTTP endpoint documentation for the QweN Daemon API.

**Base URL**: `http://127.0.0.1:5997`

## Endpoints Overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check and status |
| GET | `/v1/profiles` | List agent profiles |
| GET | `/v1/profiles/{name}/tools` | Get profile tools |
| GET | `/v1/tools` | List all tools |
| GET | `/v1/tools/{name}` | Get tool spec |
| POST | `/v1/tools/{name}/invoke` | Invoke tool directly |
| POST | `/v1/chat` | Stateless chat completion |
| GET | `/v1/sessions` | List sessions |
| POST | `/v1/sessions` | Create session |
| GET | `/v1/sessions/{id}` | Get session |
| DELETE | `/v1/sessions/{id}` | Delete session |
| POST | `/v1/sessions/{id}/chat` | Chat in session |
| POST | `/v1/sessions/{id}/chat/stream` | Streaming chat (SSE) |
| GET | `/v1/generation/status` | Generation queue status |

---

## Health

### GET /health

Check daemon health and get current status.

**Response** `200 OK`

```json
{
  "status": "healthy",
  "model_loaded": true,
  "model_size": "LARGE",
  "generation_in_progress": false,
  "available_profiles": ["mirror", "code_runner", "general"],
  "available_tools": ["get_current_datetime", "search_linear_issues", "..."]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always "healthy" if responding |
| `model_loaded` | boolean | Whether model is loaded in memory |
| `model_size` | string \| null | Current model size (SMALL/MEDIUM/LARGE) |
| `generation_in_progress` | boolean | Whether inference is currently running |
| `available_profiles` | string[] | List of profile names |
| `available_tools` | string[] | List of tool names |

---

## Profiles

### GET /v1/profiles

List all available agent profiles.

**Response** `200 OK`

```json
[
  {
    "name": "mirror",
    "system_prompt_preview": "You are a knowledge assistant with access to...",
    "tool_names": ["get_current_datetime", "search_linear_issues", "..."],
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

### GET /v1/profiles/{profile_name}/tools

Get tools available for a specific profile.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `profile_name` | string | Profile name (e.g., "mirror") |

**Response** `200 OK`

```json
[
  {
    "name": "get_current_datetime",
    "description": "Get the current date and time...",
    "parameters": {
      "type": "object",
      "properties": {},
      "required": []
    }
  }
]
```

**Errors**

- `404 Not Found`: Unknown profile name

---

## Tools

### GET /v1/tools

List all available tools with their specifications.

**Response** `200 OK`

```json
[
  {
    "name": "get_current_datetime",
    "description": "Get the current date and time. ALWAYS call this first when answering questions about time periods...",
    "parameters": {
      "type": "object",
      "properties": {},
      "required": []
    }
  },
  {
    "name": "search_linear_issues",
    "description": "Search Linear issues by keyword...",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "Search term to match in issue title or description"
        },
        "state": {
          "type": "string",
          "description": "Filter by state name (e.g., 'Todo', 'In Progress', 'Done')"
        },
        "limit": {
          "type": "integer",
          "description": "Max results per page (default 10)"
        }
      },
      "required": []
    }
  }
]
```

### GET /v1/tools/{tool_name}

Get a specific tool's specification.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `tool_name` | string | Tool name |

**Response** `200 OK`

```json
{
  "name": "browser_navigate",
  "description": "Navigate browser to a URL. Returns page title and final URL.",
  "parameters": {
    "type": "object",
    "properties": {
      "url": {
        "type": "string",
        "description": "The URL to navigate to"
      }
    },
    "required": ["url"]
  }
}
```

**Errors**

- `404 Not Found`: Unknown tool name

### POST /v1/tools/{tool_name}/invoke

Invoke a tool directly without LLM involvement.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `tool_name` | string | Tool name |

**Request Body**

```json
{
  "arguments": {
    "query": "authentication",
    "state": "In Progress"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `arguments` | object | No | Tool arguments (defaults to `{}`) |

**Response** `200 OK`

```json
{
  "tool_name": "search_linear_issues",
  "result": {
    "total": 3,
    "page": 0,
    "issues": [...]
  },
  "latency_ms": 45.2
}
```

**Errors**

- `404 Not Found`: Unknown tool name

---

## Chat (Stateless)

### POST /v1/chat

Single chat completion without session persistence.

**Request Body**

```json
{
  "message": "What Linear issues are in progress?",
  "profile": "mirror",
  "model_size": "large",
  "history": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi there!"}
  ],
  "verbose": false
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `message` | string | Yes | - | User message to process |
| `profile` | string | No | "general" | Agent profile name |
| `model_size` | string | No | "large" | Model size: small, medium, large |
| `history` | array | No | `[]` | Prior conversation history |
| `verbose` | boolean | No | false | Enable verbose logging |

**Response** `200 OK`

```json
{
  "content": "Based on my search, there are 5 issues currently in progress...",
  "tool_calls": [
    {
      "name": "search_linear_issues",
      "arguments": {"state": "In Progress"}
    }
  ],
  "tool_results": [
    {
      "tool_name": "search_linear_issues",
      "result": "{\"total\": 5, \"issues\": [...]}"
    }
  ],
  "rounds_used": 2,
  "finished": true,
  "latency_ms": 3456.7
}
```

| Field | Type | Description |
|-------|------|-------------|
| `content` | string | Final response text |
| `tool_calls` | array | Tools invoked during generation |
| `tool_results` | array | Results from tool invocations |
| `rounds_used` | integer | Number of inference rounds |
| `finished` | boolean | Whether generation completed normally |
| `latency_ms` | number | Total processing time |

**Errors**

- `400 Bad Request`: Invalid model_size or unknown profile

---

## Sessions

### GET /v1/sessions

List all sessions (summaries only, most recent first).

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 50 | Maximum sessions to return |

**Response** `200 OK`

```json
[
  {
    "id": "session-abc123",
    "profile_name": "mirror",
    "title": "What's happening with the migration?",
    "created_at": 1704672000.0,
    "updated_at": 1704675600.0,
    "message_count": 4
  }
]
```

### POST /v1/sessions

Create a new session.

**Request Body**

```json
{
  "profile_name": "mirror"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `profile_name` | string | No | "general" | Profile for this session |

**Response** `200 OK`

```json
{
  "id": "session-abc123",
  "profile_name": "mirror",
  "created_at": 1704672000.0,
  "updated_at": 1704672000.0,
  "messages": [],
  "title": null
}
```

### GET /v1/sessions/{session_id}

Get a session with full message history.

**Response** `200 OK`

```json
{
  "id": "session-abc123",
  "profile_name": "mirror",
  "created_at": 1704672000.0,
  "updated_at": 1704675600.0,
  "title": "What's happening with the migration?",
  "messages": [
    {
      "id": "msg-xyz789",
      "role": "user",
      "content": "What's happening with the migration?",
      "timestamp": 1704672000.0,
      "tool_calls": [],
      "tool_results": []
    },
    {
      "id": "msg-xyz790",
      "role": "assistant",
      "content": "Based on Linear, the migration project has...",
      "timestamp": 1704672030.0,
      "tool_calls": [{"name": "search_linear_issues", "arguments": {...}}],
      "tool_results": [{"tool_name": "search_linear_issues", "result": "..."}]
    }
  ]
}
```

**Errors**

- `404 Not Found`: Session not found

### DELETE /v1/sessions/{session_id}

Delete a session.

**Response** `200 OK`

```json
{
  "deleted": true
}
```

**Errors**

- `404 Not Found`: Session not found

### POST /v1/sessions/{session_id}/chat

Send a message in a session (blocking).

**Request Body**

```json
{
  "message": "Can you show me more details?",
  "model_size": "large",
  "verbose": false
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `message` | string | Yes | - | User message |
| `model_size` | string | No | "large" | Model size |
| `verbose` | boolean | No | false | Enable verbose logging |

**Response** `200 OK`

```json
{
  "session": {
    "id": "session-abc123",
    "messages": [...]
  },
  "response": {
    "content": "Here are the details...",
    "tool_calls": [...],
    "tool_results": [...],
    "rounds_used": 1,
    "finished": true,
    "latency_ms": 2345.6
  },
  "queue_stats": {
    "was_queued": false,
    "queue_wait_ms": 0.0,
    "queue_position": 0
  }
}
```

### POST /v1/sessions/{session_id}/chat/stream

Send a message with SSE streaming for real-time progress.

See [Streaming](streaming.md) for detailed event documentation.

**Request Body**

Same as `/v1/sessions/{id}/chat`

**Response** `200 OK` (text/event-stream)

```
data: {"type": "round_start", "round": 1, "max_rounds": 8, "timestamp": 1704672000.0}

data: {"type": "generating", "round": 1, "max_rounds": 8, "timestamp": 1704672001.0}

data: {"type": "tool_start", "tool_name": "search_linear_issues", "tool_args": {...}, "timestamp": 1704672005.0}

data: {"type": "tool_end", "tool_name": "search_linear_issues", "tool_result": "...", "timestamp": 1704672006.0}

data: {"type": "complete", "session": {...}, "response": {...}, "queue_stats": {...}, "timestamp": 1704672010.0}
```

---

## Generation Status

### GET /v1/generation/status

Get current generation queue status.

**Response** `200 OK`

```json
{
  "generating_session_id": "session-abc123",
  "queued_session_ids": ["session-def456", "session-ghi789"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `generating_session_id` | string \| null | Session currently generating |
| `queued_session_ids` | string[] | Sessions waiting in queue |

---

## Error Responses

All endpoints return errors in a consistent format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

| Status Code | Description |
|-------------|-------------|
| 400 | Bad Request - Invalid input |
| 404 | Not Found - Resource doesn't exist |
| 503 | Service Unavailable - Queue timeout |
