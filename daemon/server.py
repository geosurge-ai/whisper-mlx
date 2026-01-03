"""
FastAPI server for Qwen daemon.

Endpoints:
- GET  /health           - Health check and model status
- POST /v1/chat          - Chat completion with profile/tools
- POST /v1/invoke-tool   - Direct tool invocation (optional)
- GET  /v1/profiles      - List available agent profiles
- GET  /v1/tools         - List available tools

Startup behavior:
- Model is loaded lazily on first /v1/chat request (not at startup)
- This allows quick server restarts for config changes
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import (
    AGENT_PROFILES,
    ALL_TOOL_SPECS,
    ModelSize,
    get_tools_for_profile,
)
from .chat import (
    ChatMessage,
    ChatService,
    create_chat_service,
)
from .tools import get_registry


# --- Request/Response Models ---


class ChatMessageInput(BaseModel):
    """Input message in conversation history."""
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


def _empty_history() -> list[ChatMessageInput]:
    return []

def _empty_dict_list() -> list[dict[str, Any]]:
    return []


class ChatRequest(BaseModel):
    """Request body for /v1/chat endpoint."""
    message: str = Field(..., description="User message to process")
    profile: str = Field(default="general", description="Agent profile name")
    model_size: str = Field(default="large", description="Model size: small, medium, large")
    history: list[ChatMessageInput] = Field(default_factory=_empty_history, description="Prior conversation history")
    verbose: bool = Field(default=False, description="Enable verbose logging")


class ChatResponseModel(BaseModel):
    """Response body for /v1/chat endpoint."""
    content: str = Field(..., description="Final response content")
    tool_calls: list[dict[str, Any]] = Field(default_factory=_empty_dict_list, description="Tool calls made")
    tool_results: list[dict[str, Any]] = Field(default_factory=_empty_dict_list, description="Tool results received")
    rounds_used: int = Field(..., description="Number of inference rounds")
    finished: bool = Field(..., description="Whether response completed normally")
    latency_ms: float = Field(..., description="Total processing time in milliseconds")


class ToolInvokeRequest(BaseModel):
    """Request body for /v1/invoke-tool endpoint."""
    tool_name: str = Field(..., description="Name of tool to invoke")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class ToolInvokeResponse(BaseModel):
    """Response body for /v1/invoke-tool endpoint."""
    tool_name: str
    result: Any
    latency_ms: float


class HealthResponse(BaseModel):
    """Response body for /health endpoint."""
    status: str
    model_loaded: bool
    model_size: str | None
    available_profiles: list[str]
    available_tools: list[str]


class ProfileInfo(BaseModel):
    """Info about an agent profile."""
    name: str
    system_prompt_preview: str
    tool_names: list[str]
    max_tool_rounds: int


class ToolInfo(BaseModel):
    """Info about a tool."""
    name: str
    description: str
    parameters: dict[str, Any]


# --- Application State ---

class AppState:
    """Mutable application state."""
    
    def __init__(self) -> None:
        self._chat_services: dict[ModelSize, ChatService] = {}
        self._current_model_size: ModelSize | None = None
        self._model_loaded: bool = False
    
    def get_chat_service(self, model_size: ModelSize) -> ChatService:
        """Get or create chat service for model size."""
        if model_size not in self._chat_services:
            self._chat_services[model_size] = create_chat_service(model_size)
        self._current_model_size = model_size
        self._model_loaded = True  # Model loads on first chat request
        return self._chat_services[model_size]
    
    @property
    def model_loaded(self) -> bool:
        """Check if any model is currently loaded."""
        return self._model_loaded
    
    @property
    def current_model_size(self) -> ModelSize | None:
        """Get current model size."""
        return self._current_model_size


app_state = AppState()


# --- Application Setup ---

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for startup/shutdown."""
    print("🚀 Qwen Daemon starting...")
    print(f"   Available profiles: {list(AGENT_PROFILES.keys())}")
    print(f"   Available tools: {list(ALL_TOOL_SPECS.keys())}")
    print("   Model will load on first request.")
    yield
    print("👋 Qwen Daemon shutting down...")


app = FastAPI(
    title="Qwen Daemon",
    description="Unified LLM service with centralized tools and prompts",
    version="0.1.0",
    lifespan=lifespan,
)


# --- Endpoints ---

@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint with model status."""
    return HealthResponse(
        status="healthy",
        model_loaded=app_state.model_loaded,
        model_size=app_state.current_model_size.name if app_state.current_model_size else None,
        available_profiles=list(AGENT_PROFILES.keys()),
        available_tools=get_registry().available_tools,
    )


@app.post("/v1/chat", response_model=ChatResponseModel)
async def chat(request: ChatRequest) -> ChatResponseModel:
    """
    Chat completion endpoint.
    
    Processes user message with the specified agent profile,
    executing tools as needed and returning the final response.
    """
    start_time = time.perf_counter()
    
    # Parse model size
    size_map: dict[str, ModelSize] = {
        "small": ModelSize.SMALL,
        "medium": ModelSize.MEDIUM,
        "large": ModelSize.LARGE,
    }
    model_size = size_map.get(request.model_size.lower())
    if model_size is None:
        raise HTTPException(status_code=400, detail=f"Invalid model_size: {request.model_size}")
    
    # Validate profile
    if request.profile not in AGENT_PROFILES:
        raise HTTPException(status_code=400, detail=f"Unknown profile: {request.profile}")
    
    # Get chat service (loads model if needed)
    service = app_state.get_chat_service(model_size)
    
    # Convert history
    history: list[ChatMessage] = [
        ChatMessage(m.role, m.content)
        for m in request.history
    ]
    
    # Process chat
    result = service.chat(
        user_message=request.message,
        profile_name=request.profile,
        conversation_history=history,
        verbose=request.verbose,
    )
    
    latency_ms = (time.perf_counter() - start_time) * 1000
    
    return ChatResponseModel(
        content=result.content,
        tool_calls=[{"name": tc.name, "arguments": tc.arguments} for tc in result.tool_calls],
        tool_results=[{"tool_name": tr.tool_name, "result": tr.result} for tr in result.tool_results],
        rounds_used=result.rounds_used,
        finished=result.finished,
        latency_ms=latency_ms,
    )


@app.post("/v1/invoke-tool", response_model=ToolInvokeResponse)
async def invoke_tool(request: ToolInvokeRequest) -> ToolInvokeResponse:
    """
    Direct tool invocation endpoint.
    
    Executes a tool directly without LLM involvement.
    Useful for testing tools or scripted workflows.
    """
    start_time = time.perf_counter()
    
    registry = get_registry()
    if request.tool_name not in registry.available_tools:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {request.tool_name}")
    
    result = registry.execute(request.tool_name, request.arguments)
    
    # Parse result if it's JSON
    parsed_result: Any
    try:
        parsed_result = json.loads(result)
    except json.JSONDecodeError:
        parsed_result = result
    
    latency_ms = (time.perf_counter() - start_time) * 1000
    
    return ToolInvokeResponse(
        tool_name=request.tool_name,
        result=parsed_result,
        latency_ms=latency_ms,
    )


@app.get("/v1/profiles", response_model=list[ProfileInfo])
async def list_profiles() -> list[ProfileInfo]:
    """List available agent profiles."""
    return [
        ProfileInfo(
            name=name,
            system_prompt_preview=profile.system_prompt[:200] + "..." if len(profile.system_prompt) > 200 else profile.system_prompt,
            tool_names=list(profile.tool_names),
            max_tool_rounds=profile.max_tool_rounds,
        )
        for name, profile in AGENT_PROFILES.items()
    ]


@app.get("/v1/tools", response_model=list[ToolInfo])
async def list_tools() -> list[ToolInfo]:
    """List available tools."""
    return [
        ToolInfo(
            name=spec.name,
            description=spec.description,
            parameters=spec.parameters,
        )
        for spec in ALL_TOOL_SPECS.values()
    ]


@app.get("/v1/profiles/{profile_name}/tools", response_model=list[ToolInfo])
async def get_profile_tools(profile_name: str) -> list[ToolInfo]:
    """Get tools available for a specific profile."""
    if profile_name not in AGENT_PROFILES:
        raise HTTPException(status_code=404, detail=f"Unknown profile: {profile_name}")
    
    tools = get_tools_for_profile(profile_name)
    return [
        ToolInfo(
            name=spec.name,
            description=spec.description,
            parameters=spec.parameters,
        )
        for spec in tools
    ]


# --- CLI Entry Point ---

def main() -> None:
    """Run the daemon server."""
    import sys
    import uvicorn
    
    host = "127.0.0.1"
    port = 8421
    
    # Parse CLI args
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--host" and i + 1 < len(args):
            host = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        else:
            i += 1
    
    print(f"Starting Qwen Daemon on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
