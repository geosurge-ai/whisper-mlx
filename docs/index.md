# QweN Daemon

A local LLM service powered by MLX with integrated tool execution, session management, and real-time streaming.

## What is QweN Daemon?

QweN Daemon is a FastAPI server that wraps Qwen models running on Apple Silicon via MLX. It provides:

- **Tool Integration**: LLM-mediated and direct tool invocation
- **Session Management**: Persistent conversation history with automatic context handling
- **Agent Profiles**: Pre-configured personas with curated tool sets
- **Real-time Streaming**: SSE-based progress updates during generation
- **Generation Queue**: Serialized model access preventing concurrent inference conflicts

## Quick Start

### Prerequisites

- macOS with Apple Silicon (M1/M2/M3)
- Python 3.11+
- MLX and mlx-lm installed

### Starting the Daemon

```bash
# From project root
./run-daemon
```

The daemon starts on `http://127.0.0.1:5997` by default.

### Health Check

```bash
curl http://127.0.0.1:5997/health
```

```json
{
  "status": "healthy",
  "model_loaded": true,
  "model_size": "LARGE",
  "generation_in_progress": false,
  "available_profiles": ["mirror", "code_runner", "general"],
  "available_tools": ["get_current_datetime", "search_linear_issues", ...]
}
```

## Common Workflows

### 1. Simple Chat (Stateless)

Send a message and get a response without session context:

```bash
curl -X POST http://127.0.0.1:5997/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is 2 + 2?",
    "profile": "general"
  }'
```

### 2. Session-Based Chat (Stateful)

For multi-turn conversations with history:

```bash
# Create a session
curl -X POST http://127.0.0.1:5997/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"profile_name": "mirror"}'

# Chat in the session
curl -X POST http://127.0.0.1:5997/v1/sessions/{session_id}/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What Linear issues are in progress?"}'
```

### 3. Direct Tool Invocation

Call tools directly without LLM involvement:

```bash
curl -X POST http://127.0.0.1:5997/v1/tools/get_current_datetime/invoke \
  -H "Content-Type: application/json" \
  -d '{"arguments": {}}'
```

## Documentation

| Document | Description |
|----------|-------------|
| [API Reference](api-reference.md) | Complete HTTP endpoint documentation |
| [Sessions](sessions.md) | Session lifecycle, history, and queue management |
| [Tools](tools.md) | Tool system, invocation, and creating custom tools |
| [Profiles](profiles.md) | Agent profiles and customization |
| [Streaming](streaming.md) | Real-time SSE events during generation |
| [Architecture](architecture.md) | Internal design and data flow |

## Model Sizes

The daemon supports three model configurations:

| Size | Model ID | VRAM | Use Case |
|------|----------|------|----------|
| `small` | Qwen2.5-7B-Instruct-4bit | ~5GB | Fast iteration, simple queries |
| `medium` | Qwen2.5-14B-Instruct-4bit | ~10GB | Balanced performance |
| `large` | Qwen3-32B-4bit | ~18GB | Best quality (default) |

Specify model size in chat requests:

```json
{
  "message": "...",
  "model_size": "medium"
}
```

## Base URL

All API endpoints are served from:

```
http://127.0.0.1:5997
```

For frontend development, the Vite dev server proxies `/api` to this address.
