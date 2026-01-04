"""
FastAPI server for Qwen daemon.

Endpoints:
- GET  /health           - Health check and model status
- POST /v1/chat          - Chat completion with profile/tools
- POST /v1/invoke-tool   - Direct tool invocation (optional)
- GET  /v1/profiles      - List available agent profiles
- GET  /v1/tools         - List available tools

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
from typing import Any, AsyncIterator

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('qwen.server')

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
from .sessions import get_session_store, Session


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
    """Request body for /v1/invoke-tool endpoint."""

    tool_name: str = Field(..., description="Name of tool to invoke")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Tool arguments"
    )


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


# --- Application State ---


class AppState:
    """Mutable application state with generation lock and queue tracking."""

    def __init__(self) -> None:
        self._chat_services: dict[ModelSize, ChatService] = {}
        self._current_model_size: ModelSize | None = None
        self._model_loaded: bool = False
        # Semaphore for model generation - only one at a time on M4
        self._generation_lock: asyncio.Lock = asyncio.Lock()
        self._generation_in_progress: bool = False
        # Queue tracking for generation status
        self._generating_session_id: str | None = None
        self._queued_session_ids: list[str] = []
        # Thread lock for atomic queue operations (concurrent requests)
        self._queue_lock: threading.Lock = threading.Lock()
        # Position counter - monotonically increasing, tracks arrival order
        # Maps session_id -> position when it was first added
        self._position_map: dict[str, int] = {}
        self._next_position: int = 0

    @property
    def generation_lock(self) -> asyncio.Lock:
        """Get the generation lock for serializing model access."""
        return self._generation_lock

    @property
    def is_generating(self) -> bool:
        """Check if generation is currently in progress."""
        return self._generation_in_progress

    def set_generating(self, value: bool, session_id: str | None = None) -> None:
        """Set generation status and optionally the generating session ID.

        NOTE: We do NOT remove from queue here - that's done by remove_from_queue
        when generation is fully complete. Removing early would cause later arrivals
        to see an empty queue and get incorrect position calculations.
        """
        with self._queue_lock:
            logger.debug(f"set_generating({value}, session={session_id}) - was generating: {self._generation_in_progress}")
            self._generation_in_progress = value
            if value and session_id:
                self._generating_session_id = session_id
                logger.info(f"🔄 Generation STARTED for session {session_id[:8]}...")
            elif not value:
                logger.info(f"✅ Generation FINISHED for session {self._generating_session_id[:8] if self._generating_session_id else 'unknown'}")
                self._generating_session_id = None

    def add_to_queue(self, session_id: str) -> int:
        """Add a session to the queue and return its position atomically.
        
        Position is a monotonically increasing counter representing arrival order:
        - 0 means first to arrive in this batch
        - 1 means second to arrive
        - etc.
        
        The counter resets when the queue becomes completely empty (no pending
        requests). This gives meaningful positions within a batch of concurrent
        requests.
        """
        with self._queue_lock:
            # Check if already has a position (shouldn't happen, but be safe)
            if session_id in self._position_map:
                logger.debug(f"Session {session_id[:8]} already in queue at position {self._position_map[session_id]}")
                return self._position_map[session_id]
            
            # Get next position from counter
            position = self._next_position
            self._next_position += 1
            
            # Record position and add to queue
            self._position_map[session_id] = position
            if session_id not in self._queued_session_ids:
                self._queued_session_ids.append(session_id)
            
            queue_size = len(self._queued_session_ids)
            logger.info(f"📥 Session {session_id[:8]} added to queue at position {position} (queue size: {queue_size})")
            return position

    def remove_from_queue(self, session_id: str) -> None:
        """Remove a session from the queue (on completion or error).
        
        NOTE: We intentionally do NOT reset the position counter here.
        Resetting when queue is empty would cause a race condition where
        a request that completes before others arrive causes later requests
        to get position 0 again.
        
        The counter grows monotonically - positions indicate relative arrival
        order. For overlapping requests, positions 0, 1, 2 mean first, second,
        third to arrive. For non-overlapping requests, positions might be
        10, 11, 12 but the relative order is still meaningful.
        """
        with self._queue_lock:
            was_in_queue = session_id in self._queued_session_ids
            was_generating = self._generating_session_id == session_id
            
            if session_id in self._queued_session_ids:
                self._queued_session_ids.remove(session_id)
            if session_id in self._position_map:
                del self._position_map[session_id]
            if self._generating_session_id == session_id:
                self._generating_session_id = None
            
            queue_size = len(self._queued_session_ids)
            logger.info(f"📤 Session {session_id[:8]} removed from queue (was_in_queue={was_in_queue}, was_generating={was_generating}, remaining: {queue_size})")

    def get_generation_status(self) -> GenerationStatus:
        """Get current generation queue status."""
        with self._queue_lock:
            return GenerationStatus(
                generating_session_id=self._generating_session_id,
                queued_session_ids=list(self._queued_session_ids),
            )

    def get_chat_service(self, model_size: ModelSize) -> ChatService:
        """Get or create chat service for model size."""
        if model_size not in self._chat_services:
            logger.info(f"🔧 Creating new chat service for model size: {model_size.name}")
            start_time = time.time()
            self._chat_services[model_size] = create_chat_service(model_size)
            elapsed = time.time() - start_time
            logger.info(f"✅ Chat service created in {elapsed:.1f}s")
        else:
            logger.debug(f"Reusing existing chat service for {model_size.name}")
        self._current_model_size = model_size
        self._model_loaded = True
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
    logger.info("🚀 Qwen Daemon starting...")
    logger.info(f"   Available profiles: {list(AGENT_PROFILES.keys())}")
    logger.info(f"   Available tools: {list(ALL_TOOL_SPECS.keys())}")
    
    # Prune ALL empty sessions on startup (max_age=0 means delete all empty)
    store = get_session_store()
    pruned = store.prune_empty(max_age_seconds=0)
    if pruned > 0:
        logger.info(f"   🗑️ Pruned {pruned} empty session(s) on startup")
    
    # Pre-load the model at startup so first request doesn't freeze
    logger.info("   Loading model (this may take 30-60 seconds)...")
    start_time = time.time()
    _ = app_state.get_chat_service(ModelSize.LARGE)
    elapsed = time.time() - start_time
    logger.info(f"   ✓ Model loaded and ready in {elapsed:.1f}s!")
    
    yield
    
    # Cleanup browser on shutdown
    logger.info("👋 Qwen Daemon shutting down...")
    try:
        from .browser import get_browser_manager
        browser_manager = get_browser_manager()
        if browser_manager.is_running:
            await browser_manager.close()
    except Exception as e:
        logger.warning(f"Error closing browser: {e}")


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
    is_gen = app_state.is_generating
    logger.debug(f"GET /health - model_loaded={app_state.model_loaded}, generating={is_gen}")
    return HealthResponse(
        status="healthy",
        model_loaded=app_state.model_loaded,
        model_size=(
            app_state.current_model_size.name if app_state.current_model_size else None
        ),
        generation_in_progress=is_gen,
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
        raise HTTPException(
            status_code=400, detail=f"Invalid model_size: {request.model_size}"
        )

    # Validate profile
    if request.profile not in AGENT_PROFILES:
        raise HTTPException(
            status_code=400, detail=f"Unknown profile: {request.profile}"
        )

    # Get chat service (loads model if needed)
    service = app_state.get_chat_service(model_size)

    # Convert history
    history: list[ChatMessage] = [
        ChatMessage(m.role, m.content) for m in request.history
    ]

    # Process chat using async method (supports async tools like browser)
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


@app.post("/v1/invoke-tool", response_model=ToolInvokeResponse)
async def invoke_tool(request: ToolInvokeRequest) -> ToolInvokeResponse:
    """
    Direct tool invocation endpoint.

    Executes a tool directly without LLM involvement.
    Useful for testing tools or scripted workflows.
    Supports both sync and async tools.
    """
    start_time = time.perf_counter()

    registry = get_registry()
    if request.tool_name not in registry.available_tools:
        raise HTTPException(
            status_code=404, detail=f"Unknown tool: {request.tool_name}"
        )

    # Use async execution to support both sync and async tools
    result = await registry.execute_async(request.tool_name, request.arguments)

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
            system_prompt_preview=(
                profile.system_prompt[:200] + "..."
                if len(profile.system_prompt) > 200
                else profile.system_prompt
            ),
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
    """
    Get current generation queue status.

    Returns:
    - generating_session_id: Session currently generating (or null if idle)
    - queued_session_ids: Sessions waiting for their turn
    """
    status = app_state.get_generation_status()
    if status.generating_session_id or status.queued_session_ids:
        logger.debug(f"GET /v1/generation/status - generating={status.generating_session_id[:8] if status.generating_session_id else None}, queued={len(status.queued_session_ids)}")
    return status


@app.get("/v1/sessions", response_model=list[SessionSummaryModel])
async def list_sessions(limit: int = 50) -> list[SessionSummaryModel]:
    """List all sessions (summaries only, sorted by most recent)."""
    store = get_session_store()
    # Prune empty sessions older than 60 seconds before listing
    pruned = store.prune_empty(max_age_seconds=60)
    if pruned > 0:
        logger.info(f"🗑️ Pruned {pruned} empty session(s)")
    summaries = store.list_summaries(limit=limit)
    logger.debug(f"GET /v1/sessions - returning {len(summaries)} sessions")
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
    if request.profile_name not in AGENT_PROFILES:
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
    """
    Send a message in a session.

    This endpoint:
    1. Acquires the generation lock (only one generation at a time)
    2. Loads the session from disk
    3. Adds the user message
    4. Generates a response using the model
    5. Adds the assistant message
    6. Saves the session to disk
    7. Returns the updated session and response

    If another generation is in progress, this request will wait (with timeout).
    """
    start_time = time.perf_counter()
    logger.info(f"📨 POST /v1/sessions/{session_id[:8]}.../chat - message: {request.message[:50]}...")

    # Validate model size
    size_map: dict[str, ModelSize] = {
        "small": ModelSize.SMALL,
        "medium": ModelSize.MEDIUM,
        "large": ModelSize.LARGE,
    }
    model_size = size_map.get(request.model_size.lower())
    if model_size is None:
        logger.error(f"Invalid model_size: {request.model_size}")
        raise HTTPException(
            status_code=400, detail=f"Invalid model_size: {request.model_size}"
        )

    # Load session
    store = get_session_store()
    session = store.get(session_id)
    if session is None:
        logger.error(f"Session not found: {session_id}")
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    logger.debug(f"Loaded session: profile={session.profile_name}, messages={len(session.messages)}")

    # Validate profile
    if session.profile_name not in AGENT_PROFILES:
        logger.error(f"Unknown profile: {session.profile_name}")
        raise HTTPException(
            status_code=400, detail=f"Unknown profile: {session.profile_name}"
        )

    # Add user message immediately (before generation)
    session.add_message(role="user", content=request.message)
    logger.debug(f"Added user message to session, now has {len(session.messages)} messages")

    # Add to queue and get position atomically
    queue_position = app_state.add_to_queue(session_id)
    queue_enter_time = time.perf_counter()

    # Cooperative yield: let other concurrent requests add to queue
    # before we try to acquire the generation lock. Without this,
    # the first request acquires the lock immediately and runs its
    # synchronous model generation to completion before any other
    # request even calls add_to_queue().
    await asyncio.sleep(0)

    logger.debug(f"Session {session_id[:8]} waiting for generation lock...")

    # Track whether we acquired the lock (for cleanup in timeout handler)
    acquired_lock = False

    # Acquire generation lock with timeout
    # 30 minute timeout covers both lock wait AND generation
    # Complex browser automation tasks can take 10+ minutes per tool call
    try:
        async with asyncio.timeout(1800):
            async with app_state.generation_lock:
                acquired_lock = True
                # Calculate queue wait time
                lock_acquired_time = time.perf_counter()
                queue_wait_ms = (lock_acquired_time - queue_enter_time) * 1000
                was_queued = queue_wait_ms > 10  # Consider >10ms as "was queued"
                
                logger.info(f"🔓 Session {session_id[:8]} acquired lock (waited {queue_wait_ms:.0f}ms, position={queue_position})")

                # Mark as generating (moves from queued to generating)
                app_state.set_generating(True, session_id=session_id)
                try:
                    # Get chat service (loads model if needed)
                    service = app_state.get_chat_service(model_size)

                    # Build history from session messages
                    history: list[ChatMessage] = [
                        ChatMessage(msg.role, msg.content)
                        for msg in session.messages[:-1]  # Exclude the user message we just added
                    ]

                    logger.info(f"🤖 Starting generation for session {session_id[:8]} with {len(history)} history messages...")
                    gen_start = time.perf_counter()
                    
                    # Generate response using async chat (supports async tools like browser)
                    result = await service.chat_async(
                        user_message=request.message,
                        profile_name=session.profile_name,
                        conversation_history=history,
                        verbose=request.verbose,
                    )
                    
                    gen_elapsed = (time.perf_counter() - gen_start) * 1000
                    logger.info(f"🤖 Generation complete for session {session_id[:8]} in {gen_elapsed:.0f}ms (rounds={result.rounds_used}, tools={len(result.tool_calls)})")

                    # Add assistant message
                    session.add_message(
                        role="assistant",
                        content=result.content,
                        tool_calls=[{"name": tc.name, "arguments": tc.arguments} for tc in result.tool_calls],
                        tool_results=[{"tool_name": tr.tool_name, "result": tr.result} for tr in result.tool_results],
                    )

                    # Save session
                    store.save(session)
                    logger.debug(f"Session {session_id[:8]} saved with {len(session.messages)} messages")

                finally:
                    # Clear generation status (always runs if lock was acquired)
                    app_state.set_generating(False)
                    app_state.remove_from_queue(session_id)

    except asyncio.TimeoutError:
        # Only cleanup if we never acquired the lock (timed out waiting)
        # If we did acquire it, the finally block already handled cleanup
        if not acquired_lock:
            logger.error(f"⏰ Session {session_id[:8]} timed out waiting for lock after 30 minutes")
            app_state.remove_from_queue(session_id)
            raise HTTPException(
                status_code=503,
                detail="Timed out after 30 minutes waiting for another request to finish.",
            )
        else:
            # Timeout during generation (finally block already cleaned up)
            logger.error(f"⏰ Session {session_id[:8]} generation timed out after 30 minutes")
            raise HTTPException(
                status_code=503,
                detail="Generation timed out after 30 minutes. Try a simpler request.",
            )

    latency_ms = (time.perf_counter() - start_time) * 1000

    # Build response
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


# --- CLI Entry Point ---


def main() -> None:
    """Run the daemon server."""
    import sys
    import uvicorn

    host = "127.0.0.1"
    port = 5997

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
