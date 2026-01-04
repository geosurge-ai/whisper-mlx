# QweN Daemon API

Local-only API for tool invocation and LLM chat.

## Base URL

```
http://127.0.0.1:5997
```

## Endpoints

### Health

```bash
GET /health
```

Returns daemon status, loaded model, available profiles and tools.

### Tools (Local-Only)

List all tools:
```bash
GET /v1/tools
```

Get tool spec:
```bash
GET /v1/tools/{tool_name}
```

Invoke tool directly (no LLM):
```bash
POST /v1/tools/{tool_name}/invoke
Content-Type: application/json

{"arguments": {"query": "test"}}
```

### Profiles

List profiles:
```bash
GET /v1/profiles
```

Get tools for profile:
```bash
GET /v1/profiles/{profile_name}/tools
```

### Chat

Single chat completion:
```bash
POST /v1/chat
Content-Type: application/json

{
  "message": "What time is it?",
  "profile": "mirror",
  "model_size": "large"
}
```

### Sessions

```bash
POST /v1/sessions                    # Create session
GET  /v1/sessions                    # List sessions
GET  /v1/sessions/{id}               # Get session
DELETE /v1/sessions/{id}             # Delete session
POST /v1/sessions/{id}/chat          # Chat in session
POST /v1/sessions/{id}/chat/stream   # Chat with SSE streaming
```

## Available Profiles

| Profile | Tools | Use Case |
|---------|-------|----------|
| `mirror` | Linear, Slack, Python | Team knowledge queries |
| `code_runner` | Browser automation | Run code in online playgrounds |
| `general` | None | Basic conversation |

## Example: Direct Tool Call

```bash
curl -X POST http://127.0.0.1:5997/v1/tools/get_current_datetime/invoke \
  -H "Content-Type: application/json" \
  -d '{"arguments": {}}'
```

## Example: Chat with Tools

```bash
curl -X POST http://127.0.0.1:5997/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What Linear issues are in progress?",
    "profile": "mirror"
  }'
```
