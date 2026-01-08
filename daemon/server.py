"""
FastAPI server for Qwen daemon.

Endpoints:
- GET  /health           - Health check and model status
- POST /v1/chat          - Chat completion with profile/tools
- POST /v1/invoke-tool   - Direct tool invocation (local-only API)
- GET  /v1/tools         - List all available tools
- GET  /v1/tools/{name}  - Get tool spec by name
- POST /v1/tools/{name}/invoke - Invoke specific tool (local-only API)
- GET  /v1/profiles      - List available agent profiles
- GET  /v1/profiles/{name}/tools - Get tools for a profile

Startup behavior:
- Model is pre-loaded at startup for fast first response
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Literal

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('qwen.server')

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .tools import get_registry, ToolSpec
from .profiles import ALL_PROFILES, get_profile
from .chat import (
    ChatMessage,
    ChatService,
    create_chat_service,
    ModelSize,
)
from .sessions import get_session_store, Session

# Import session context functions for tool execution
from .tools.mirror.data_store import set_session_context, reset_session_context


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
    model_size: str = Field(
        default="large", description="Model size: small, medium, large"
    )
    history: list[ChatMessageInput] = Field(
        default_factory=_empty_history, description="Prior conversation history"
    )
    verbose: bool = Field(default=False, description="Enable verbose logging")


class ChatResponseModel(BaseModel):
    """Response body for /v1/chat endpoint."""

    content: str = Field(..., description="Final response content")
    tool_calls: list[dict[str, Any]] = Field(
        default_factory=_empty_dict_list, description="Tool calls made"
    )
    tool_results: list[dict[str, Any]] = Field(
        default_factory=_empty_dict_list, description="Tool results received"
    )
    rounds_used: int = Field(..., description="Number of inference rounds")
    finished: bool = Field(..., description="Whether response completed normally")
    latency_ms: float = Field(..., description="Total processing time in milliseconds")


class ToolInvokeRequest(BaseModel):
    """Request body for tool invocation endpoints."""

    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Tool arguments"
    )


class LegacyToolInvokeRequest(BaseModel):
    """Legacy request body for /v1/invoke-tool endpoint."""

    tool_name: str = Field(..., description="Name of tool to invoke")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Tool arguments"
    )


class ToolInvokeResponse(BaseModel):
    """Response body for tool invocation endpoints."""

    tool_name: str
    result: Any
    latency_ms: float


class HealthResponse(BaseModel):
    """Response body for /health endpoint."""

    status: str
    model_loaded: bool
    model_size: str | None
    generation_in_progress: bool
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


# --- Session Models ---


def _empty_tool_list() -> list[dict[str, Any]]:
    return []


class SessionMessageModel(BaseModel):
    """A message within a session."""

    id: str
    role: str
    content: str
    timestamp: float
    tool_calls: list[dict[str, Any]] = Field(default_factory=_empty_tool_list)
    tool_results: list[dict[str, Any]] = Field(default_factory=_empty_tool_list)


def _empty_message_list() -> list[SessionMessageModel]:
    return []


class SessionModel(BaseModel):
    """A conversation session."""

    id: str
    profile_name: str
    created_at: float
    updated_at: float
    messages: list[SessionMessageModel] = Field(default_factory=_empty_message_list)
    title: str | None = None


class SessionSummaryModel(BaseModel):
    """Session summary without full messages."""

    id: str
    profile_name: str
    title: str | None
    created_at: float
    updated_at: float
    message_count: int


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""

    profile_name: str = Field(default="general", description="Profile to use for this session")


class SessionChatRequest(BaseModel):
    """Request to send a message in a session."""

    message: str = Field(..., description="User message")
    model_size: str = Field(default="large", description="Model size: small, medium, large")
    verbose: bool = Field(default=False, description="Enable verbose logging")


class QueueStats(BaseModel):
    """Statistics about queue wait time for a request."""

    was_queued: bool = Field(
        ..., description="Whether this request had to wait in queue"
    )
    queue_wait_ms: float = Field(
        ..., description="Time spent waiting in queue (ms)"
    )
    queue_position: int = Field(
        ..., description="Position in queue when request started (0 = immediate)"
    )


class SessionChatResponse(BaseModel):
    """Response from session chat."""

    session: SessionModel
    response: ChatResponseModel
    queue_stats: QueueStats = Field(
        ..., description="Queue statistics for this request"
    )


def _empty_queued_list() -> list[str]:
    return []


class GenerationStatus(BaseModel):
    """Current generation queue status."""

    generating_session_id: str | None = Field(
        None, description="Session ID currently generating, or null if idle"
    )
    queued_session_ids: list[str] = Field(
        default_factory=_empty_queued_list,
        description="Session IDs waiting in queue",
    )


# --- SSE Event Types ---


class GenerationEvent(BaseModel):
    """Server-Sent Event for generation progress."""

    type: Literal["round_start", "generating", "tool_start", "tool_end", "complete", "error"]
    round: int | None = Field(None, description="Current round number (1-indexed)")
    max_rounds: int | None = Field(None, description="Maximum rounds allowed")
    tool_name: str | None = Field(None, description="Tool being executed")
    tool_args: dict[str, Any] | None = Field(None, description="Tool arguments (truncated)")
    session: SessionModel | None = Field(None, description="Final session state (on complete)")
    response: ChatResponseModel | None = Field(None, description="Final response (on complete)")
    queue_stats: QueueStats | None = Field(None, description="Queue stats (on complete)")
    error: str | None = Field(None, description="Error message (on error)")
    timestamp: float = Field(default_factory=time.time, description="Event timestamp")


# --- Application State ---


class AppState:
    """Mutable application state with generation lock and queue tracking."""

    def __init__(self) -> None:
        self._chat_services: dict[ModelSize, ChatService] = {}
        self._current_model_size: ModelSize | None = None
        self._model_loaded: bool = False
        self._generation_lock: asyncio.Lock = asyncio.Lock()
        self._generation_in_progress: bool = False
        self._generating_session_id: str | None = None
        self._queued_session_ids: list[str] = []
        self._queue_lock: threading.Lock = threading.Lock()
        self._position_map: dict[str, int] = {}
        self._next_position: int = 0

    @property
    def generation_lock(self) -> asyncio.Lock:
        return self._generation_lock

    @property
    def is_generating(self) -> bool:
        return self._generation_in_progress

    def set_generating(self, value: bool, session_id: str | None = None) -> None:
        with self._queue_lock:
            logger.debug(f"set_generating({value}, session={session_id})")
            self._generation_in_progress = value
            if value and session_id:
                self._generating_session_id = session_id
                logger.info(f"🔄 Generation STARTED for session {session_id[:8]}...")
            elif not value:
                logger.info(f"✅ Generation FINISHED for session {self._generating_session_id[:8] if self._generating_session_id else 'unknown'}")
                self._generating_session_id = None

    def add_to_queue(self, session_id: str) -> int:
        with self._queue_lock:
            if session_id in self._position_map:
                return self._position_map[session_id]

            position = self._next_position
            self._next_position += 1
            self._position_map[session_id] = position
            if session_id not in self._queued_session_ids:
                self._queued_session_ids.append(session_id)

            logger.info(f"📥 Session {session_id[:8]} added to queue at position {position}")
            return position

    def remove_from_queue(self, session_id: str) -> None:
        with self._queue_lock:
            if session_id in self._queued_session_ids:
                self._queued_session_ids.remove(session_id)
            if session_id in self._position_map:
                del self._position_map[session_id]
            if self._generating_session_id == session_id:
                self._generating_session_id = None
            logger.info(f"📤 Session {session_id[:8]} removed from queue")

    def get_generation_status(self) -> GenerationStatus:
        with self._queue_lock:
            return GenerationStatus(
                generating_session_id=self._generating_session_id,
                queued_session_ids=list(self._queued_session_ids),
            )

    def get_chat_service(self, model_size: ModelSize) -> ChatService:
        if model_size not in self._chat_services:
            logger.info(f"🔧 Creating new chat service for model size: {model_size.name}")
            start_time = time.time()
            self._chat_services[model_size] = create_chat_service(model_size)
            elapsed = time.time() - start_time
            logger.info(f"✅ Chat service created in {elapsed:.1f}s")
        self._current_model_size = model_size
        self._model_loaded = True
        return self._chat_services[model_size]

    @property
    def model_loaded(self) -> bool:
        return self._model_loaded

    @property
    def current_model_size(self) -> ModelSize | None:
        return self._current_model_size


app_state = AppState()


# --- Application Setup ---


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for startup/shutdown."""
    logger.info("🚀 Qwen Daemon starting...")
    logger.info(f"   Available profiles: {list(ALL_PROFILES.keys())}")
    logger.info(f"   Available tools: {get_registry().available_tools}")

    store = get_session_store()
    pruned = store.prune_empty(max_age_seconds=0)
    if pruned > 0:
        logger.info(f"   🗑️ Pruned {pruned} empty session(s) on startup")

    logger.info("   Loading model (this may take 30-60 seconds)...")
    start_time = time.time()
    _ = app_state.get_chat_service(ModelSize.LARGE)
    elapsed = time.time() - start_time
    logger.info(f"   ✓ Model loaded and ready in {elapsed:.1f}s!")

    # Start Google sync scheduler (runs every 5 minutes)
    try:
        from .sync.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.warning(f"Failed to start sync scheduler: {e}")

    yield

    logger.info("👋 Qwen Daemon shutting down...")

    # Stop sync scheduler
    try:
        from .sync.scheduler import stop_scheduler
        stop_scheduler()
    except Exception as e:
        logger.warning(f"Error stopping sync scheduler: {e}")

    try:
        from .tools.browser.manager import get_browser_manager
        browser_manager = get_browser_manager()
        if browser_manager.is_running:
            await browser_manager.close()
    except Exception as e:
        logger.warning(f"Error closing browser: {e}")


app = FastAPI(
    title="Qwen Daemon",
    description="Unified LLM service with centralized tools and prompts",
    version="0.2.0",
    lifespan=lifespan,
)


# --- Health Endpoint ---


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint with model status."""
    return HealthResponse(
        status="healthy",
        model_loaded=app_state.model_loaded,
        model_size=(
            app_state.current_model_size.name if app_state.current_model_size else None
        ),
        generation_in_progress=app_state.is_generating,
        available_profiles=list(ALL_PROFILES.keys()),
        available_tools=get_registry().available_tools,
    )


# --- Tool API Endpoints (Local-Only) ---


@app.get("/v1/tools", response_model=list[ToolInfo])
async def list_tools() -> list[ToolInfo]:
    """List all available tools with their specs."""
    registry = get_registry()
    specs = registry.get_all_specs()
    return [
        ToolInfo(
            name=spec.name,
            description=spec.description,
            parameters=spec.parameters,
        )
        for spec in specs.values()
    ]


@app.get("/v1/tools/{tool_name}", response_model=ToolInfo)
async def get_tool(tool_name: str) -> ToolInfo:
    """Get a specific tool's spec by name."""
    registry = get_registry()
    spec = registry.get_spec(tool_name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    return ToolInfo(
        name=spec.name,
        description=spec.description,
        parameters=spec.parameters,
    )


@app.post("/v1/tools/{tool_name}/invoke", response_model=ToolInvokeResponse)
async def invoke_tool_by_name(tool_name: str, request: ToolInvokeRequest) -> ToolInvokeResponse:
    """
    Invoke a specific tool directly (local-only API).

    This endpoint allows direct tool execution without LLM involvement.
    Supports both sync and async tools.
    """
    start_time = time.perf_counter()

    registry = get_registry()
    if tool_name not in registry.available_tools:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")

    result = await registry.execute_async(tool_name, request.arguments)

    parsed_result: Any
    try:
        parsed_result = json.loads(result)
    except json.JSONDecodeError:
        parsed_result = result

    latency_ms = (time.perf_counter() - start_time) * 1000

    return ToolInvokeResponse(
        tool_name=tool_name,
        result=parsed_result,
        latency_ms=latency_ms,
    )


@app.post("/v1/invoke-tool", response_model=ToolInvokeResponse)
async def invoke_tool_legacy(request: LegacyToolInvokeRequest) -> ToolInvokeResponse:
    """
    Legacy tool invocation endpoint (for backwards compatibility).

    Use POST /v1/tools/{name}/invoke instead.
    """
    start_time = time.perf_counter()

    registry = get_registry()
    if request.tool_name not in registry.available_tools:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {request.tool_name}")

    result = await registry.execute_async(request.tool_name, request.arguments)

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


# --- Profile Endpoints ---


@app.get("/v1/profiles", response_model=list[ProfileInfo])
async def list_profiles() -> list[ProfileInfo]:
    """List available agent profiles."""
    return [
        ProfileInfo(
            name=profile.name,
            system_prompt_preview=(
                profile.system_prompt[:200] + "..."
                if len(profile.system_prompt) > 200
                else profile.system_prompt
            ),
            tool_names=list(profile.tool_names),
            max_tool_rounds=profile.max_tool_rounds,
        )
        for profile in ALL_PROFILES.values()
    ]


@app.get("/v1/profiles/{profile_name}/tools", response_model=list[ToolInfo])
async def get_profile_tools(profile_name: str) -> list[ToolInfo]:
    """Get tools available for a specific profile."""
    profile = get_profile(profile_name)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Unknown profile: {profile_name}")

    return [
        ToolInfo(
            name=tool.name,
            description=tool.description,
            parameters=tool.parameters,
        )
        for tool in profile.tools
    ]


# --- Chat Endpoint ---


@app.post("/v1/chat", response_model=ChatResponseModel)
async def chat(request: ChatRequest) -> ChatResponseModel:
    """Chat completion endpoint."""
    start_time = time.perf_counter()

    size_map: dict[str, ModelSize] = {
        "small": ModelSize.SMALL,
        "medium": ModelSize.MEDIUM,
        "large": ModelSize.LARGE,
    }
    model_size = size_map.get(request.model_size.lower())
    if model_size is None:
        raise HTTPException(
            status_code=400, detail=f"Invalid model_size: {request.model_size}"
        )

    if request.profile not in ALL_PROFILES:
        raise HTTPException(
            status_code=400, detail=f"Unknown profile: {request.profile}"
        )

    service = app_state.get_chat_service(model_size)

    history: list[ChatMessage] = [
        ChatMessage(m.role, m.content) for m in request.history
    ]

    result = await service.chat_async(
        user_message=request.message,
        profile_name=request.profile,
        conversation_history=history,
        verbose=request.verbose,
    )

    latency_ms = (time.perf_counter() - start_time) * 1000

    return ChatResponseModel(
        content=result.content,
        tool_calls=[
            {"name": tc.name, "arguments": tc.arguments} for tc in result.tool_calls
        ],
        tool_results=[
            {"tool_name": tr.tool_name, "result": tr.result}
            for tr in result.tool_results
        ],
        rounds_used=result.rounds_used,
        finished=result.finished,
        latency_ms=latency_ms,
    )


# --- Session Endpoints ---


def _session_to_model(session: Session) -> SessionModel:
    """Convert internal Session to Pydantic SessionModel."""
    return SessionModel(
        id=session.id,
        profile_name=session.profile_name,
        created_at=session.created_at,
        updated_at=session.updated_at,
        title=session.title,
        messages=[
            SessionMessageModel(
                id=msg.id,
                role=msg.role,
                content=msg.content,
                timestamp=msg.timestamp,
                tool_calls=msg.tool_calls,
                tool_results=msg.tool_results,
            )
            for msg in session.messages
        ],
    )


@app.get("/v1/generation/status", response_model=GenerationStatus)
async def get_generation_status() -> GenerationStatus:
    """Get current generation queue status."""
    return app_state.get_generation_status()


@app.get("/v1/sessions", response_model=list[SessionSummaryModel])
async def list_sessions(limit: int = 50) -> list[SessionSummaryModel]:
    """List all sessions (summaries only, sorted by most recent)."""
    store = get_session_store()
    pruned = store.prune_empty(max_age_seconds=60)
    if pruned > 0:
        logger.info(f"🗑️ Pruned {pruned} empty session(s)")
    summaries = store.list_summaries(limit=limit)
    return [
        SessionSummaryModel(
            id=s["id"],
            profile_name=s["profile_name"],
            title=s["title"],
            created_at=s["created_at"],
            updated_at=s["updated_at"],
            message_count=s["message_count"],
        )
        for s in summaries
    ]


@app.post("/v1/sessions", response_model=SessionModel)
async def create_session(request: CreateSessionRequest) -> SessionModel:
    """Create a new session."""
    if request.profile_name not in ALL_PROFILES:
        raise HTTPException(
            status_code=400, detail=f"Unknown profile: {request.profile_name}"
        )

    store = get_session_store()
    session = store.create(request.profile_name)
    return _session_to_model(session)


@app.get("/v1/sessions/{session_id}", response_model=SessionModel)
async def get_session(session_id: str) -> SessionModel:
    """Get a session by ID."""
    store = get_session_store()
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return _session_to_model(session)


@app.delete("/v1/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, bool]:
    """Delete a session."""
    store = get_session_store()
    deleted = store.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return {"deleted": True}


@app.post("/v1/sessions/{session_id}/chat", response_model=SessionChatResponse)
async def session_chat(session_id: str, request: SessionChatRequest) -> SessionChatResponse:
    """Send a message in a session."""
    start_time = time.perf_counter()
    logger.info(f"📨 POST /v1/sessions/{session_id[:8]}.../chat")

    size_map: dict[str, ModelSize] = {
        "small": ModelSize.SMALL,
        "medium": ModelSize.MEDIUM,
        "large": ModelSize.LARGE,
    }
    model_size = size_map.get(request.model_size.lower())
    if model_size is None:
        raise HTTPException(
            status_code=400, detail=f"Invalid model_size: {request.model_size}"
        )

    store = get_session_store()
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if session.profile_name not in ALL_PROFILES:
        raise HTTPException(
            status_code=400, detail=f"Unknown profile: {session.profile_name}"
        )

    session.add_message(role="user", content=request.message)

    queue_position = app_state.add_to_queue(session_id)
    queue_enter_time = time.perf_counter()

    await asyncio.sleep(0)

    acquired_lock = False

    try:
        async with asyncio.timeout(1800):
            async with app_state.generation_lock:
                acquired_lock = True
                lock_acquired_time = time.perf_counter()
                queue_wait_ms = (lock_acquired_time - queue_enter_time) * 1000
                was_queued = queue_wait_ms > 10

                logger.info(f"🔓 Session {session_id[:8]} acquired lock (waited {queue_wait_ms:.0f}ms)")

                app_state.set_generating(True, session_id=session_id)
                try:
                    service = app_state.get_chat_service(model_size)

                    history: list[ChatMessage] = [
                        ChatMessage(msg.role, msg.content)
                        for msg in session.messages[:-1]
                    ]

                    context_token = set_session_context(session_id)
                    try:
                        result = await service.chat_async(
                            user_message=request.message,
                            profile_name=session.profile_name,
                            conversation_history=history,
                            verbose=request.verbose,
                        )
                    finally:
                        reset_session_context(context_token)

                    session.add_message(
                        role="assistant",
                        content=result.content,
                        tool_calls=[{"name": tc.name, "arguments": tc.arguments} for tc in result.tool_calls],
                        tool_results=[{"tool_name": tr.tool_name, "result": tr.result} for tr in result.tool_results],
                    )

                    store.save(session)

                finally:
                    app_state.set_generating(False)
                    app_state.remove_from_queue(session_id)

    except asyncio.TimeoutError:
        if not acquired_lock:
            app_state.remove_from_queue(session_id)
            raise HTTPException(
                status_code=503,
                detail="Timed out after 30 minutes waiting for another request to finish.",
            )
        else:
            raise HTTPException(
                status_code=503,
                detail="Generation timed out after 30 minutes.",
            )

    latency_ms = (time.perf_counter() - start_time) * 1000

    chat_response = ChatResponseModel(
        content=result.content,
        tool_calls=[{"name": tc.name, "arguments": tc.arguments} for tc in result.tool_calls],
        tool_results=[{"tool_name": tr.tool_name, "result": tr.result} for tr in result.tool_results],
        rounds_used=result.rounds_used,
        finished=result.finished,
        latency_ms=latency_ms,
    )

    queue_stats = QueueStats(
        was_queued=was_queued,
        queue_wait_ms=queue_wait_ms,
        queue_position=queue_position,
    )

    return SessionChatResponse(
        session=_session_to_model(session),
        response=chat_response,
        queue_stats=queue_stats,
    )


@app.post("/v1/sessions/{session_id}/chat/stream")
async def session_chat_stream(session_id: str, request: SessionChatRequest):
    """Send a message and stream generation progress via Server-Sent Events."""
    start_time = time.perf_counter()
    logger.info(f"📨 POST /v1/sessions/{session_id[:8]}.../chat/stream")

    size_map: dict[str, ModelSize] = {
        "small": ModelSize.SMALL,
        "medium": ModelSize.MEDIUM,
        "large": ModelSize.LARGE,
    }
    model_size = size_map.get(request.model_size.lower())
    if model_size is None:
        raise HTTPException(
            status_code=400, detail=f"Invalid model_size: {request.model_size}"
        )

    store = get_session_store()
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if session.profile_name not in ALL_PROFILES:
        raise HTTPException(
            status_code=400, detail=f"Unknown profile: {session.profile_name}"
        )

    session.add_message(role="user", content=request.message)

    queue_position = app_state.add_to_queue(session_id)
    queue_enter_time = time.perf_counter()

    await asyncio.sleep(0)

    async def event_generator():
        nonlocal session
        acquired_lock = False
        was_queued = False
        queue_wait_ms = 0.0

        event_queue: asyncio.Queue[dict] = asyncio.Queue()

        async def on_event(event: dict) -> None:
            await event_queue.put(event)

        try:
            async with asyncio.timeout(1800):
                async with app_state.generation_lock:
                    acquired_lock = True
                    lock_acquired_time = time.perf_counter()
                    queue_wait_ms = (lock_acquired_time - queue_enter_time) * 1000
                    was_queued = queue_wait_ms > 10

                    app_state.set_generating(True, session_id=session_id)

                    try:
                        service = app_state.get_chat_service(model_size)

                        history: list[ChatMessage] = [
                            ChatMessage(msg.role, msg.content)
                            for msg in session.messages[:-1]
                        ]

                        async def run_chat():
                            context_token = set_session_context(session_id)
                            try:
                                return await service.chat_async(
                                    user_message=request.message,
                                    profile_name=session.profile_name,
                                    conversation_history=history,
                                    verbose=request.verbose,
                                    on_event=on_event,
                                )
                            finally:
                                reset_session_context(context_token)

                        chat_task = asyncio.create_task(run_chat())

                        while not chat_task.done():
                            try:
                                event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                                yield f"data: {json.dumps(event)}\n\n"
                            except asyncio.TimeoutError:
                                continue

                        while not event_queue.empty():
                            event = event_queue.get_nowait()
                            yield f"data: {json.dumps(event)}\n\n"

                        result = await chat_task

                        session.add_message(
                            role="assistant",
                            content=result.content,
                            tool_calls=[{"name": tc.name, "arguments": tc.arguments} for tc in result.tool_calls],
                            tool_results=[{"tool_name": tr.tool_name, "result": tr.result} for tr in result.tool_results],
                        )

                        store.save(session)

                        latency_ms = (time.perf_counter() - start_time) * 1000
                        complete_event = GenerationEvent(
                            type="complete",
                            session=_session_to_model(session),
                            response=ChatResponseModel(
                                content=result.content,
                                tool_calls=[{"name": tc.name, "arguments": tc.arguments} for tc in result.tool_calls],
                                tool_results=[{"tool_name": tr.tool_name, "result": tr.result} for tr in result.tool_results],
                                rounds_used=result.rounds_used,
                                finished=result.finished,
                                latency_ms=latency_ms,
                            ),
                            queue_stats=QueueStats(
                                was_queued=was_queued,
                                queue_wait_ms=queue_wait_ms,
                                queue_position=queue_position,
                            ),
                        )
                        yield f"data: {complete_event.model_dump_json()}\n\n"

                    finally:
                        app_state.set_generating(False)
                        app_state.remove_from_queue(session_id)

        except asyncio.TimeoutError:
            if not acquired_lock:
                app_state.remove_from_queue(session_id)
                error_event = GenerationEvent(
                    type="error",
                    error="Timed out after 30 minutes waiting for another request to finish.",
                )
                yield f"data: {error_event.model_dump_json()}\n\n"
            else:
                error_event = GenerationEvent(
                    type="error",
                    error="Generation timed out after 30 minutes.",
                )
                yield f"data: {error_event.model_dump_json()}\n\n"
        except Exception as e:
            logger.error(f"❌ [STREAM] Session {session_id[:8]} error: {e}")
            error_event = GenerationEvent(
                type="error",
                error=str(e),
            )
            yield f"data: {error_event.model_dump_json()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- CLI Entry Point ---


def main() -> None:
    """Run the daemon server."""
    import sys
    import uvicorn

    host = "127.0.0.1"
    port = 5997

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
