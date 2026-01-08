# Sessions

Sessions provide persistent, stateful conversations with automatic history management.

## Overview

Unlike the stateless `/v1/chat` endpoint, sessions:

- **Persist conversation history** to disk as JSON files
- **Maintain context** across multiple requests
- **Track metadata** like creation time, title, tool usage
- **Support streaming** for real-time generation progress

## Session Lifecycle

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Create    │────▶│    Chat     │────▶│   Persist   │────▶│   Delete    │
│  Session    │     │  (repeat)   │     │  (auto)     │     │  (manual)   │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

### 1. Create Session

```bash
curl -X POST http://127.0.0.1:5997/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"profile_name": "mirror"}'
```

Response:

```json
{
  "id": "session-a1b2c3d4e5f6",
  "profile_name": "mirror",
  "created_at": 1704672000.0,
  "updated_at": 1704672000.0,
  "messages": [],
  "title": null
}
```

The session ID is a UUID-based identifier used in all subsequent requests.

### 2. Chat in Session

```bash
curl -X POST http://127.0.0.1:5997/v1/sessions/session-a1b2c3d4e5f6/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What Linear issues are in progress?"}'
```

Each chat request:

1. Adds the user message to session history
2. Builds conversation context from all previous messages
3. Runs inference with the session's profile
4. Adds the assistant response (with tool data) to history
5. Auto-saves the session to disk

### 3. Retrieve Session

```bash
curl http://127.0.0.1:5997/v1/sessions/session-a1b2c3d4e5f6
```

Returns the full session with all messages and metadata.

### 4. Delete Session

```bash
curl -X DELETE http://127.0.0.1:5997/v1/sessions/session-a1b2c3d4e5f6
```

Removes the session file from disk.

## Session Storage

Sessions are stored as JSON files in `data/sessions/`:

```
data/sessions/
├── session-a1b2c3d4e5f6.json
├── session-x7y8z9w0v1u2.json
└── ...
```

Each file contains the complete session state:

```json
{
  "id": "session-a1b2c3d4e5f6",
  "profile_name": "mirror",
  "created_at": 1704672000.0,
  "updated_at": 1704675600.0,
  "title": "What Linear issues are in progress?",
  "messages": [
    {
      "id": "msg-abc123",
      "role": "user",
      "content": "What Linear issues are in progress?",
      "timestamp": 1704672000.0,
      "tool_calls": [],
      "tool_results": []
    },
    {
      "id": "msg-def456",
      "role": "assistant",
      "content": "Based on my search, there are 5 issues...",
      "timestamp": 1704672030.0,
      "tool_calls": [
        {"name": "search_linear_issues", "arguments": {"state": "In Progress"}}
      ],
      "tool_results": [
        {"tool_name": "search_linear_issues", "result": "{...}"}
      ]
    }
  ]
}
```

## Auto-Generated Titles

The session title is automatically set from the first user message (truncated to 50 characters). This provides a quick preview in session lists.

## Empty Session Pruning

Empty sessions (no messages) are automatically pruned:

- On daemon startup: All empty sessions deleted immediately
- On session list: Empty sessions older than 60 seconds deleted

This prevents accumulation of abandoned sessions from client disconnects or errors.

## Generation Queue

The daemon uses a **single-writer lock** for model inference. Only one generation can run at a time.

### Queue Behavior

When multiple sessions request generation simultaneously:

1. First request acquires the lock and starts generating
2. Subsequent requests enter a FIFO queue
3. Each queued request waits for the lock
4. Queue position is tracked and returned in responses

### Queue Stats

Every session chat response includes queue statistics:

```json
{
  "queue_stats": {
    "was_queued": true,
    "queue_wait_ms": 15234.5,
    "queue_position": 2
  }
}
```

| Field | Description |
|-------|-------------|
| `was_queued` | True if request waited >10ms for the lock |
| `queue_wait_ms` | Total time spent waiting in queue |
| `queue_position` | Position when request entered queue (0 = immediate) |

### Monitoring Queue Status

Check current queue state:

```bash
curl http://127.0.0.1:5997/v1/generation/status
```

```json
{
  "generating_session_id": "session-abc123",
  "queued_session_ids": ["session-def456", "session-ghi789"]
}
```

### Timeout Handling

Requests timeout after 30 minutes in queue (returning `503 Service Unavailable`). This prevents indefinite blocking during very long generations.

## TypeScript Client Example

Using the typed client from the frontend:

```typescript
import {
  createSession,
  sendSessionChat,
  streamSessionChat,
  getSession,
  deleteSession,
  listSessions,
} from './api/client'

// Create a new session
const session = await createSession({ profile_name: 'mirror' })
console.log('Created session:', session.id)

// Send a message (blocking)
const response = await sendSessionChat(session.id, {
  message: 'What happened in the last sprint?',
  model_size: 'large',
})
console.log('Response:', response.response.content)

// Or stream for real-time updates
await streamSessionChat(
  session.id,
  { message: 'Tell me more about the blockers' },
  (event) => {
    switch (event.type) {
      case 'round_start':
        console.log(`Round ${event.round}/${event.max_rounds}`)
        break
      case 'tool_start':
        console.log(`Calling ${event.tool_name}...`)
        break
      case 'complete':
        console.log('Done:', event.response?.content)
        break
    }
  }
)

// List all sessions
const sessions = await listSessions(10)
sessions.forEach(s => console.log(`${s.id}: ${s.title}`))

// Clean up
await deleteSession(session.id)
```

## Best Practices

### Session Reuse

Reuse sessions for related queries to maintain context. The LLM can reference earlier messages and tool results.

### Profile Selection

Choose the profile at session creation time. The profile determines:

- System prompt (agent persona)
- Available tools
- Max inference rounds

### Error Handling

Handle queue timeouts gracefully:

```typescript
try {
  const response = await sendSessionChat(sessionId, { message: '...' })
} catch (error) {
  if (error instanceof ApiError && error.status === 503) {
    // Queue timeout - try again or notify user
  }
}
```

### Cleanup

Delete sessions when done to free disk space. The frontend typically tracks "active" sessions and deletes old ones.
