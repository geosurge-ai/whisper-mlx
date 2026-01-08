# Streaming

Real-time generation progress via Server-Sent Events (SSE).

## Overview

The streaming endpoint provides live updates during chat generation:

- **Round progress**: When inference rounds start
- **Tool execution**: When tools are called and complete
- **Thinking content**: Model's reasoning (Qwen3 hybrid thinking)
- **Completion**: Final response and session state

This enables responsive UIs that show generation progress rather than blocking until completion.

## Endpoint

```
POST /v1/sessions/{session_id}/chat/stream
```

**Request Body** (same as non-streaming chat):

```json
{
  "message": "What happened in the last sprint?",
  "model_size": "large",
  "verbose": false
}
```

**Response**: `text/event-stream`

## Event Types

### round_start

Emitted when a new inference round begins.

```json
{
  "type": "round_start",
  "round": 1,
  "max_rounds": 8,
  "timestamp": 1704672000.0
}
```

| Field | Type | Description |
|-------|------|-------------|
| `round` | integer | Current round number (1-indexed) |
| `max_rounds` | integer | Maximum rounds allowed by profile |

### generating

Emitted when the model starts generating.

```json
{
  "type": "generating",
  "round": 1,
  "max_rounds": 8,
  "timestamp": 1704672001.0
}
```

### thinking

Emitted when the model produces thinking content (Qwen3 hybrid reasoning).

```json
{
  "type": "thinking",
  "content": "Let me search for sprint-related issues first...",
  "round": 1,
  "max_rounds": 8,
  "timestamp": 1704672002.0
}
```

| Field | Type | Description |
|-------|------|-------------|
| `content` | string | Full thinking content (never truncated) |

### tool_start

Emitted when a tool execution begins.

```json
{
  "type": "tool_start",
  "tool_name": "search_linear_issues",
  "tool_args": {
    "query": "sprint",
    "state": "Done"
  },
  "round": 1,
  "max_rounds": 8,
  "timestamp": 1704672003.0
}
```

| Field | Type | Description |
|-------|------|-------------|
| `tool_name` | string | Name of tool being executed |
| `tool_args` | object | Arguments passed to tool |

### tool_end

Emitted when a tool execution completes.

```json
{
  "type": "tool_end",
  "tool_name": "search_linear_issues",
  "tool_result": "{\"total\": 15, \"issues\": [...]}",
  "round": 1,
  "max_rounds": 8,
  "timestamp": 1704672004.0
}
```

| Field | Type | Description |
|-------|------|-------------|
| `tool_name` | string | Name of completed tool |
| `tool_result` | string | JSON-encoded tool result |

### complete

Emitted when generation finishes successfully.

```json
{
  "type": "complete",
  "session": {
    "id": "session-abc123",
    "profile_name": "mirror",
    "messages": [...],
    "title": "...",
    "created_at": 1704672000.0,
    "updated_at": 1704672010.0
  },
  "response": {
    "content": "Based on the sprint data, here's what happened...",
    "tool_calls": [...],
    "tool_results": [...],
    "rounds_used": 2,
    "finished": true,
    "latency_ms": 10234.5
  },
  "queue_stats": {
    "was_queued": false,
    "queue_wait_ms": 0.0,
    "queue_position": 0
  },
  "timestamp": 1704672010.0
}
```

| Field | Type | Description |
|-------|------|-------------|
| `session` | object | Complete session with all messages |
| `response` | object | Chat response details |
| `queue_stats` | object | Queue wait statistics |

### error

Emitted when an error occurs.

```json
{
  "type": "error",
  "error": "Tool execution failed: Connection timeout",
  "timestamp": 1704672005.0
}
```

| Field | Type | Description |
|-------|------|-------------|
| `error` | string | Error message |

## Event Stream Format

Events follow the SSE specification:

```
data: {"type": "round_start", "round": 1, "max_rounds": 8, "timestamp": 1704672000.0}

data: {"type": "generating", "round": 1, "max_rounds": 8, "timestamp": 1704672001.0}

data: {"type": "tool_start", "tool_name": "search_linear_issues", ...}

data: {"type": "tool_end", "tool_name": "search_linear_issues", ...}

data: {"type": "complete", "session": {...}, "response": {...}, ...}
```

Each event is:
- Prefixed with `data: `
- JSON-encoded
- Followed by two newlines (`\n\n`)

## TypeScript Client

The frontend client includes a typed streaming implementation:

```typescript
import { streamSessionChat, GenerationEvent } from './api/client'

await streamSessionChat(
  sessionId,
  { message: 'What happened last sprint?', model_size: 'large' },
  (event: GenerationEvent) => {
    switch (event.type) {
      case 'round_start':
        console.log(`Round ${event.round}/${event.max_rounds}`)
        setStatus('thinking')
        break

      case 'thinking':
        console.log('Model thinking:', event.content)
        break

      case 'tool_start':
        console.log(`Calling ${event.tool_name}...`)
        setStatus(`Executing ${event.tool_name}`)
        break

      case 'tool_end':
        console.log(`${event.tool_name} completed`)
        break

      case 'complete':
        console.log('Done:', event.response?.content)
        setSession(event.session!)
        setStatus('idle')
        break

      case 'error':
        console.error('Error:', event.error)
        setError(event.error!)
        break
    }
  }
)
```

## JavaScript/Browser Implementation

Raw SSE handling with fetch:

```javascript
async function streamChat(sessionId, message, onEvent) {
  const response = await fetch(`/api/v1/sessions/${sessionId}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    // Parse SSE events
    const lines = buffer.split('\n')
    buffer = lines.pop() // Keep incomplete line

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6).trim()
        if (data) {
          try {
            const event = JSON.parse(data)
            onEvent(event)
          } catch (e) {
            console.warn('Failed to parse event:', data)
          }
        }
      }
    }
  }
}

// Usage
streamChat('session-abc', 'What happened last week?', (event) => {
  if (event.type === 'tool_start') {
    showSpinner(`Running ${event.tool_name}...`)
  } else if (event.type === 'complete') {
    hideSpinner()
    showResponse(event.response.content)
  }
})
```

## Python Client

Using `httpx` for SSE:

```python
import httpx
import json

async def stream_chat(session_id: str, message: str):
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            f"http://127.0.0.1:5997/v1/sessions/{session_id}/chat/stream",
            json={"message": message},
            timeout=None,
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:].strip()
                    if data:
                        event = json.loads(data)
                        yield event

# Usage
async for event in stream_chat("session-abc", "What's happening?"):
    if event["type"] == "tool_start":
        print(f"Calling {event['tool_name']}...")
    elif event["type"] == "complete":
        print(f"Response: {event['response']['content']}")
```

## Event Timeline

Typical event sequence for a tool-using query:

```
Time    Event
─────   ─────────────────────────────────────────
0ms     round_start (round=1)
10ms    generating (round=1)
2000ms  thinking (if Qwen3 hybrid mode)
2500ms  tool_start (search_linear_issues)
2800ms  tool_end (search_linear_issues)
2810ms  round_start (round=2)
2820ms  generating (round=2)
5000ms  complete
```

## Error Handling

### Connection Errors

Handle network failures:

```typescript
try {
  await streamSessionChat(sessionId, request, onEvent)
} catch (error) {
  if (error instanceof NetworkError) {
    // Connection lost
    showReconnectPrompt()
  } else if (error instanceof ApiError) {
    // Server error (400, 404, 503, etc.)
    showError(error.detail || error.message)
  }
}
```

### Stream Errors

The `error` event type signals generation failures:

```typescript
case 'error':
  // Generation failed but stream is intact
  setError(event.error)
  // Stream will end after this event
  break
```

### Queue Timeout

If the generation queue times out (30 minutes), an error event is emitted:

```json
{
  "type": "error",
  "error": "Timed out after 30 minutes waiting for another request to finish.",
  "timestamp": 1704672000.0
}
```

## UI Patterns

### Progress Indicator

Show meaningful status during generation:

```typescript
const statusMessages = {
  round_start: 'Thinking...',
  generating: 'Generating response...',
  thinking: 'Reasoning...',
  tool_start: (e) => `Running ${e.tool_name}...`,
  tool_end: 'Processing results...',
  complete: 'Done',
  error: 'Error occurred',
}
```

### Activity Log

Display tool execution history:

```typescript
const [activities, setActivities] = useState([])

// In event handler
case 'tool_start':
  setActivities(prev => [...prev, {
    tool: event.tool_name,
    args: event.tool_args,
    status: 'running',
    startTime: Date.now(),
  }])
  break

case 'tool_end':
  setActivities(prev => prev.map(a =>
    a.tool === event.tool_name && a.status === 'running'
      ? { ...a, status: 'complete', result: event.tool_result }
      : a
  ))
  break
```

### Abort Support

Note: The current implementation doesn't support client-initiated abort. Closing the connection will stop receiving events but won't cancel server-side generation. The generation will complete and the session will be updated.
