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

# External dependencies - type stubs may not be available in all environments
from fastapi import FastAPI, HTTPException  # pyright: ignore[reportMissingImports]
from pydantic import BaseModel, Field  # pyright: ignore[reportMissingImports]

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
# Using BaseModel from pydantic for automatic validation

class ChatMessageInput(BaseModel):  # pyright: ignore[reportUntypedBaseClass]
    """Input message in conversation history."""
    role: str = Field(..., description="Message role: 'user' or 'assistant'")  # pyright: ignore[reportUnknownVariableType]
    content: str = Field(..., description="Message content")  # pyright: ignore[reportUnknownVariableType]


class ChatRequest(BaseModel):  # pyright: ignore[reportUntypedBaseClass]
    """Request body for /v1/chat endpoint."""
    message: str = Field(..., description="User message to process")  # pyright: ignore[reportUnknownVariableType]
    profile: str = Field(default="general", description="Agent profile name")  # pyright: ignore[reportUnknownVariableType]
    model_size: str = Field(default="large", description="Model size: small, medium, large")  # pyright: ignore[reportUnknownVariableType]
    history: list[ChatMessageInput] = Field(default_factory=list, description="Prior conversation history")  # pyright: ignore[reportUnknownVariableType]
    verbose: bool = Field(default=False, description="Enable verbose logging")  # pyright: ignore[reportUnknownVariableType]


class ChatResponseModel(BaseModel):  # pyright: ignore[reportUntypedBaseClass]
    """Response body for /v1/chat endpoint."""
    content: str = Field(..., description="Final response content")  # pyright: ignore[reportUnknownVariableType]
    tool_calls: list[dict[str, Any]] = Field(default_factory=list, description="Tool calls made")  # pyright: ignore[reportUnknownVariableType]
    tool_results: list[dict[str, Any]] = Field(default_factory=list, description="Tool results received")  # pyright: ignore[reportUnknownVariableType]
    rounds_used: int = Field(..., description="Number of inference rounds")  # pyright: ignore[reportUnknownVariableType]
    finished: bool = Field(..., description="Whether response completed normally")  # pyright: ignore[reportUnknownVariableType]
    latency_ms: float = Field(..., description="Total processing time in milliseconds")  # pyright: ignore[reportUnknownVariableType]


class ToolInvokeRequest(BaseModel):  # pyright: ignore[reportUntypedBaseClass]
    """Request body for /v1/invoke-tool endpoint."""
    tool_name: str = Field(..., description="Name of tool to invoke")  # pyright: ignore[reportUnknownVariableType]
    arguments: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")  # pyright: ignore[reportUnknownVariableType]


class ToolInvokeResponse(BaseModel):  # pyright: ignore[reportUntypedBaseClass]
    """Response body for /v1/invoke-tool endpoint."""
    tool_name: str  # pyright: ignore[reportUnknownVariableType]
    result: Any  # pyright: ignore[reportUnknownVariableType]
    latency_ms: float  # pyright: ignore[reportUnknownVariableType]


class HealthResponse(BaseModel):  # pyright: ignore[reportUntypedBaseClass]
    """Response body for /health endpoint."""
    status: str  # pyright: ignore[reportUnknownVariableType]
    model_loaded: bool  # pyright: ignore[reportUnknownVariableType]
    model_size: str | None  # pyright: ignore[reportUnknownVariableType]
    available_profiles: list[str]  # pyright: ignore[reportUnknownVariableType]
    available_tools: list[str]  # pyright: ignore[reportUnknownVariableType]


class ProfileInfo(BaseModel):  # pyright: ignore[reportUntypedBaseClass]
    """Info about an agent profile."""
    name: str  # pyright: ignore[reportUnknownVariableType]
    system_prompt_preview: str  # pyright: ignore[reportUnknownVariableType]
    tool_names: list[str]  # pyright: ignore[reportUnknownVariableType]
    max_tool_rounds: int  # pyright: ignore[reportUnknownVariableType]


class ToolInfo(BaseModel):  # pyright: ignore[reportUntypedBaseClass]
    """Info about a tool."""
    name: str  # pyright: ignore[reportUnknownVariableType]
    description: str  # pyright: ignore[reportUnknownVariableType]
    parameters: dict[str, Any]  # pyright: ignore[reportUnknownVariableType]


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
async def lifespan(app: Any) -> AsyncIterator[None]:
    """Lifespan context manager for startup/shutdown."""
    print("🚀 Qwen Daemon starting...")
    print(f"   Available profiles: {list(AGENT_PROFILES.keys())}")
    print(f"   Available tools: {list(ALL_TOOL_SPECS.keys())}")
    print("   Model will load on first request.")
    yield
    print("👋 Qwen Daemon shutting down...")


app: Any = FastAPI(
    title="Qwen Daemon",
    description="Unified LLM service with centralized tools and prompts",
    version="0.1.0",
    lifespan=lifespan,
)


# --- Endpoints ---

@app.get("/health", response_model=HealthResponse)  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
async def health_check() -> HealthResponse:
    """Health check endpoint with model status."""
    return HealthResponse(
        status="healthy",
        model_loaded=app_state.model_loaded,
        model_size=app_state.current_model_size.name if app_state.current_model_size else None,
        available_profiles=list(AGENT_PROFILES.keys()),
        available_tools=get_registry().available_tools,
    )


@app.post("/v1/chat", response_model=ChatResponseModel)  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
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
    model_size = size_map.get(request.model_size.lower())  # pyright: ignore[reportUnknownMemberType]
    if model_size is None:
        raise HTTPException(status_code=400, detail=f"Invalid model_size: {request.model_size}")  # pyright: ignore[reportUnknownMemberType]
    
    # Validate profile
    if request.profile not in AGENT_PROFILES:  # pyright: ignore[reportUnknownMemberType]
        raise HTTPException(status_code=400, detail=f"Unknown profile: {request.profile}")  # pyright: ignore[reportUnknownMemberType]
    
    # Get chat service (loads model if needed)
    service = app_state.get_chat_service(model_size)
    
    # Convert history
    history: list[ChatMessage] = [
        ChatMessage(m.role, m.content)  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        for m in request.history  # pyright: ignore[reportUnknownMemberType]
    ]
    
    # Process chat
    result = service.chat(
        user_message=request.message,  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        profile_name=request.profile,  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        conversation_history=history,
        verbose=request.verbose,  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
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


@app.post("/v1/invoke-tool", response_model=ToolInvokeResponse)  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
async def invoke_tool(request: ToolInvokeRequest) -> ToolInvokeResponse:
    """
    Direct tool invocation endpoint.
    
    Executes a tool directly without LLM involvement.
    Useful for testing tools or scripted workflows.
    """
    start_time = time.perf_counter()
    
    registry = get_registry()
    if request.tool_name not in registry.available_tools:  # pyright: ignore[reportUnknownMemberType]
        raise HTTPException(status_code=404, detail=f"Unknown tool: {request.tool_name}")  # pyright: ignore[reportUnknownMemberType]
    
    result = registry.execute(request.tool_name, request.arguments)  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
    
    # Parse result if it's JSON
    parsed_result: Any
    try:
        parsed_result = json.loads(result)
    except json.JSONDecodeError:
        parsed_result = result
    
    latency_ms = (time.perf_counter() - start_time) * 1000
    
    return ToolInvokeResponse(
        tool_name=request.tool_name,  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        result=parsed_result,
        latency_ms=latency_ms,
    )


@app.get("/v1/profiles", response_model=list[ProfileInfo])  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
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


@app.get("/v1/tools", response_model=list[ToolInfo])  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
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


@app.get("/v1/profiles/{profile_name}/tools", response_model=list[ToolInfo])  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
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
    import uvicorn  # pyright: ignore[reportMissingImports]
    
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
    uvicorn.run(app, host=host, port=port)  # pyright: ignore[reportUnknownMemberType]


if __name__ == "__main__":
    main()
