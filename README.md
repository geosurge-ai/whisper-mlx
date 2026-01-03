# Whisper + Qwen3 on MLX

Local AI stack for Apple Silicon: speech-to-text via Whisper and tool-calling LLM via Qwen3.

## Requirements

- Apple Silicon Mac (M1/M2/M3/M4)
- Nix with flakes enabled
- For Qwen3-32B: 24GB+ unified memory recommended
- For Qwen3-14B: 16GB unified memory sufficient

## Setup

```bash
# Enter the dev shell (provides Python, ffmpeg, etc.)
nix develop

# Install Python dependencies
./install
```

## Whisper (Speech-to-Text)

```bash
# Transcribe audio to text
./run input.mp3 output
# Creates output.txt
```

Uses `mlx-community/whisper-large-v3-mlx` for high-quality transcription.

## Qwen3 LLM (Tool-Calling)

### Interactive Chat

```bash
# Use large model (32B, requires ~18GB)
./run-llm

# Use medium model (14B, requires ~10GB)
./run-llm medium

# Use small model (7B, requires ~5GB)
./run-llm small
```

### Programmatic Usage

```python
from llm import ToolCallingAgent, Tool

# Define a tool
def get_weather(city: str) -> str:
    return f"Weather in {city}: Sunny, 22°C"

weather_tool = Tool(
    name="get_weather",
    description="Get current weather for a city",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name"}
        },
        "required": ["city"],
    },
    function=get_weather,
)

# Create agent with tools
agent = ToolCallingAgent(
    tools=[weather_tool],
    model_size="large",  # or "medium", "small"
)

# Run query (agent will call tools automatically)
response = agent.run("What's the weather in Tokyo?")
print(response)
```

### Available Models

| Size | Model | Memory | Best For |
|------|-------|--------|----------|
| `large` | Qwen3-32B-4bit | ~18GB | Best reasoning & tool use |
| `medium` | Qwen2.5-14B-Instruct-4bit | ~10GB | Good balance |
| `small` | Qwen2.5-7B-Instruct-4bit | ~5GB | Resource-constrained |

### Why Qwen3?

Qwen3 (April 2025) is currently the most capable open-source tool-calling LLM:
- Hybrid reasoning (thinking/non-thinking modes)
- 128K context window
- Excellent function calling via Hermes-style XML format
- Runs efficiently on Apple Silicon via MLX

## Qwen Daemon (Unified API Server)

Keep the model loaded and serve multiple agent profiles via HTTP:

```bash
# Start the daemon (loads model on first request)
./run-daemon

# In another terminal, run smoke tests
./run-ping
```

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check and model status |
| `/v1/chat` | POST | Chat completion with profile/tools |
| `/v1/invoke-tool` | POST | Direct tool execution |
| `/v1/profiles` | GET | List available agent profiles |
| `/v1/tools` | GET | List available tools |

### Example: Chat with Profile

```bash
curl -X POST http://127.0.0.1:5997/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is 2 + 2?",
    "profile": "general",
    "model_size": "large"
  }'
```

### Available Profiles

| Profile | Tools | Use Case |
|---------|-------|----------|
| `general` | None | Simple chat without tools |
| `mirror` | Linear/Slack | Query team knowledge base |
| `code_runner` | Browser/Web | Find & run code in playgrounds |

### Python Client Example

```python
import httpx

client = httpx.Client(base_url="http://127.0.0.1:5997")

# Chat with mirror profile
response = client.post("/v1/chat", json={
    "message": "What issues are in progress?",
    "profile": "mirror",
    "model_size": "large",
})
print(response.json()["content"])
```

## Architecture

```
                    ┌─────────────────────────────────────┐
                    │          Qwen Daemon                │
                    │     (FastAPI + Singleton Model)     │
                    ├─────────────────────────────────────┤
                    │  /v1/chat    /v1/invoke-tool        │
                    │  /v1/profiles  /v1/tools  /health   │
                    └──────────────────┬──────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
┌───────▼────────┐          ┌─────────▼─────────┐          ┌─────────▼─────────┐
│  AgentProfile  │          │   ToolRegistry    │          │   QwenModel       │
│  (prompts)     │          │   (executors)     │          │   (singleton)     │
└───────┬────────┘          └─────────┬─────────┘          └─────────┬─────────┘
        │                             │                              │
        │     ┌───────────────────────┴───────────────────────┐      │
        │     │                                               │      │
        │  ┌──▼───────────┐                         ┌─────────▼──┐   │
        │  │ Mirror Tools │                         │Browser Tools│  │
        │  │ (Linear/Slack)│                        │ (Playwright)│  │
        │  └──────────────┘                         └─────────────┘  │
        │                                                            │
        └────────────────────────────┬───────────────────────────────┘
                                     │
                              ┌──────▼──────┐
                              │     MLX     │
                              │  Framework  │
                              └──────┬──────┘
                                     │
                              ┌──────▼──────┐
                              │   Apple     │
                              │  Silicon    │
                              └─────────────┘
```
