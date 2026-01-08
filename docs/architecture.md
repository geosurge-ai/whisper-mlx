# Architecture

Internal design and data flow of the QweN Daemon.

## System Overview

```mermaid
graph TB
    subgraph clients [Clients]
        Frontend[React Frontend]
        CLI[CLI Tools]
        Scripts[Python Scripts]
    end

    subgraph daemon [QweN Daemon]
        Server[FastAPI Server]
        ChatService[Chat Service]
        Model[QwenModel Singleton]
        Registry[Tool Registry]
        SessionStore[Session Store]
    end

    subgraph storage [Storage]
        Sessions[(data/sessions/)]
        Models[(MLX Models)]
    end

    subgraph external [External Services]
        Linear[Linear API]
        Slack[Slack API]
        Browser[Playwright Browser]
    end

    Frontend -->|HTTP/SSE| Server
    CLI -->|HTTP| Server
    Scripts -->|HTTP| Server

    Server --> ChatService
    Server --> SessionStore
    Server --> Registry

    ChatService --> Model
    ChatService --> Registry

    Registry -->|Mirror Tools| Linear
    Registry -->|Mirror Tools| Slack
    Registry -->|Browser Tools| Browser

    SessionStore --> Sessions
    Model --> Models
```

## Request Flow

### Stateless Chat

```mermaid
sequenceDiagram
    participant C as Client
    participant S as Server
    participant CS as ChatService
    participant M as QwenModel
    participant R as Registry

    C->>S: POST /v1/chat
    S->>CS: chat_async(message, profile)

    loop Tool Rounds
        CS->>M: generate(messages)
        M-->>CS: response

        alt Has Tool Calls
            CS->>CS: parse_tool_calls()
            loop Each Tool
                CS->>R: execute_async(tool, args)
                R-->>CS: result
            end
            CS->>CS: format_tool_results()
        else No Tool Calls
            CS-->>S: ChatResponse
        end
    end

    S-->>C: JSON Response
```

### Session Chat with Streaming

```mermaid
sequenceDiagram
    participant C as Client
    participant S as Server
    participant Q as Generation Queue
    participant CS as ChatService
    participant SS as SessionStore

    C->>S: POST /sessions/{id}/chat/stream
    S->>SS: get(session_id)
    SS-->>S: Session

    S->>Q: add_to_queue(session_id)
    S->>Q: acquire_lock()

    Note over S,Q: Only one generation at a time

    S-->>C: SSE: round_start

    loop Tool Rounds
        S-->>C: SSE: generating
        S->>CS: chat_async(...)

        alt Tool Called
            S-->>C: SSE: tool_start
            CS->>CS: execute_tool()
            S-->>C: SSE: tool_end
        end
    end

    S->>SS: save(session)
    S->>Q: release_lock()
    S-->>C: SSE: complete
```

## Component Details

### FastAPI Server (`daemon/server.py`)

The HTTP layer handling:

- Request validation via Pydantic models
- Route handlers for all endpoints
- SSE streaming for real-time events
- Application lifecycle (startup/shutdown)

### Chat Service (`daemon/chat.py`)

Orchestrates the conversation flow:

```mermaid
graph LR
    subgraph ChatService
        Build[Build Messages]
        Generate[Generate]
        Parse[Parse Tool Calls]
        Execute[Execute Tools]
        Format[Format Results]
    end

    Build --> Generate
    Generate --> Parse
    Parse -->|Has calls| Execute
    Execute --> Format
    Format --> Generate
    Parse -->|No calls| Response[Response]
```

Key responsibilities:

- **Prompt Assembly**: Combines system prompt, history, and tool schemas
- **Generation**: Calls QwenModel with assembled messages
- **Tool Parsing**: Extracts `<tool_call>` blocks from responses
- **Tool Execution**: Invokes tools via registry
- **Result Injection**: Formats results as `<tool_response>` messages

### QwenModel Singleton (`daemon/chat.py`)

Manages the MLX model lifecycle:

```python
class QwenModel:
    _instance: QwenModel | None = None

    @classmethod
    def get_instance(cls, model_size: ModelSize) -> QwenModel:
        if cls._instance is None or cls._instance._model_size != model_size:
            cls._instance = cls(model_size)
        return cls._instance
```

- **Lazy Loading**: Model loaded on first inference
- **Singleton Pattern**: One model instance globally
- **Size Switching**: Can switch between small/medium/large

### Tool Registry (`daemon/tools/registry.py`)

Central registry for tool discovery and execution:

```mermaid
graph TB
    subgraph Registry
        Tools[Loaded Tools]
        Lazy[Lazy Loaders]
    end

    subgraph ToolModule
        Spec[ToolSpec]
        Func[Function]
    end

    Register[register_lazy] --> Lazy
    Get[get] --> Lazy
    Lazy -->|First Access| Import[Import Module]
    Import --> Tools
    Execute[execute_async] --> Tools
    Tools --> ToolModule
```

- **Lazy Loading**: Tools imported on first use
- **Async Support**: Handles both sync and async tool functions
- **Thread Safety**: Sync tools run in thread pool

### Session Store (`daemon/sessions.py`)

File-based persistence:

```
data/sessions/
├── session-abc123.json
├── session-def456.json
└── session-ghi789.json
```

Features:

- **Atomic Writes**: Via temp file + rename
- **Auto-pruning**: Empty sessions cleaned up
- **Sorted Listing**: Most recently updated first

## Generation Queue

The daemon enforces single-writer access to the model:

```mermaid
graph TB
    subgraph AppState
        Lock[asyncio.Lock]
        Queue[Queue Tracking]
        Status[Generation Status]
    end

    R1[Request 1] -->|Acquires| Lock
    R2[Request 2] -->|Waits| Queue
    R3[Request 3] -->|Waits| Queue

    Lock -->|Generating| Status
    Queue -->|Position| Status
```

**Why single-writer?**

- MLX models aren't thread-safe for concurrent inference
- Memory constraints on Apple Silicon
- Predictable latency (no resource contention)

## Profile System

```mermaid
graph TB
    subgraph Profile
        Name[name]
        Prompt[system_prompt]
        Tools[tools tuple]
        Settings[max_rounds, max_tokens]
    end

    subgraph Usage
        Session[Session Creation]
        Chat[Chat Request]
    end

    Profile --> Session
    Profile --> Chat
    Session -->|Inherits| Profile
```

Profiles are immutable configurations that bundle:

- Agent persona (system prompt)
- Available tools
- Inference settings

## Tool Architecture

```mermaid
graph LR
    subgraph ToolModule
        Decorator[@tool decorator]
        Spec[ToolSpec]
        Func[Function]
        Export[TOOL export]
    end

    Decorator --> Spec
    Decorator --> Func
    Spec --> Export
    Func --> Export

    subgraph Registry
        LazyRef[Lazy Reference]
        Loaded[Loaded Tool]
    end

    Export -.->|register_lazy| LazyRef
    LazyRef -->|First Use| Loaded
```

Each tool module exports a `TOOL` constant combining schema and implementation:

```python
@tool(name="...", description="...", parameters={...})
def my_tool(arg: str) -> str:
    return json.dumps({...})

TOOL = my_tool  # Tool instance with spec + execute
```

## Data Flow: Tool-Using Query

Complete flow for a query that uses tools:

```mermaid
sequenceDiagram
    participant U as User
    participant S as Server
    participant CS as Chat Service
    participant M as Model
    participant R as Registry
    participant T as Tool

    U->>S: "What issues are in progress?"
    S->>CS: chat_async(message, profile="mirror")

    CS->>CS: Build system prompt + tool schemas
    CS->>M: generate(messages)
    M-->>CS: "<tool_call>{search_linear_issues, {state: In Progress}}</tool_call>"

    CS->>CS: parse_tool_calls()
    CS->>R: execute_async("search_linear_issues", {state: "In Progress"})
    R->>T: search_linear_issues(state="In Progress")
    T-->>R: '{"total": 5, "issues": [...]}'
    R-->>CS: result

    CS->>CS: format_tool_results()
    CS->>M: generate(messages + tool_response)
    M-->>CS: "Based on my search, there are 5 issues in progress..."

    CS-->>S: ChatResponse
    S-->>U: JSON response
```

## Error Handling

```mermaid
graph TB
    subgraph Errors
        Tool[Tool Error]
        Timeout[Queue Timeout]
        Model[Model Error]
        Network[Network Error]
    end

    subgraph Handling
        ToolH[Return error JSON]
        TimeoutH[503 Service Unavailable]
        ModelH[500 Internal Error]
        NetworkH[Retry / Reconnect]
    end

    Tool --> ToolH
    Timeout --> TimeoutH
    Model --> ModelH
    Network --> NetworkH
```

- **Tool errors**: Caught and returned as JSON, LLM sees the error
- **Queue timeouts**: 503 after 30 minutes waiting
- **Model errors**: Logged and returned as 500
- **Network errors**: Client-side handling (retry, reconnect)

## Configuration

### Environment

The daemon reads configuration from:

1. Command-line args (`--host`, `--port`)
2. Default values in code

### Model Selection

```python
class ModelSize(Enum):
    SMALL = "mlx-community/Qwen2.5-7B-Instruct-4bit"
    MEDIUM = "mlx-community/Qwen2.5-14B-Instruct-4bit"
    LARGE = "mlx-community/Qwen3-32B-4bit"
```

Models are downloaded automatically on first use via Hugging Face Hub.

## Deployment

### Local Development

```bash
./run-daemon  # Starts on 127.0.0.1:5997
```

### Production Considerations

- **Single Instance**: No horizontal scaling (model in memory)
- **Memory**: 18GB+ for large model
- **Startup Time**: 30-60s for model loading
- **Persistence**: Session files require disk space
