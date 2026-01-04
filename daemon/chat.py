"""
Chat service: message assembly and tool-call handling.

Architecture:
- ChatService: orchestrates conversation flow with tool execution
- Uses singleton QwenModel for inference
- Integrates with ToolRegistry for tool execution
- Uses Profile system for configuration
- Supports both sync and async operation modes
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .tools import Tool, ToolSpec, get_registry, ToolRegistry
from .profiles import Profile, get_profile, ALL_PROFILES


# --- Message Types ---


@dataclass(frozen=True)
class ChatMessage:
    """Immutable chat message."""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass(frozen=True)
class ToolCall:
    """Parsed tool call from LLM response."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """Result from tool execution."""

    tool_name: str
    result: str


@dataclass(frozen=True)
class ChatResponse:
    """Complete response from chat service."""

    content: str
    tool_calls: tuple[ToolCall, ...]
    tool_results: tuple[ToolResult, ...]
    rounds_used: int
    finished: bool


# --- Prompt Formatting (Pure Functions) ---


def format_tools_prompt(tools: tuple[Tool, ...]) -> str:
    """Format tool specs into system prompt section."""
    if not tools:
        return ""

    schemas = [tool.to_schema() for tool in tools]
    tools_json = "\n".join(json.dumps(s) for s in schemas)

    return f"""

# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{tools_json}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{{"name": "<function-name>", "arguments": {{"<arg1>": "<value1>"}}}}
</tool_call>"""


def build_system_prompt(profile: Profile) -> str:
    """Build complete system prompt from profile and tools."""
    return profile.system_prompt + format_tools_prompt(profile.tools)


def parse_tool_calls(response: str) -> list[ToolCall]:
    """Extract tool calls from LLM response."""
    pattern = r"<tool_call>\s*({.*?})\s*</tool_call>"
    matches: list[str] = re.findall(pattern, response, re.DOTALL)

    calls: list[ToolCall] = []
    for match in matches:
        try:
            data: dict[str, Any] = json.loads(match)
            name: str = data.get("name", "")
            arguments: dict[str, Any] = data.get("arguments", {})
            calls.append(ToolCall(name=name, arguments=arguments))
        except json.JSONDecodeError:
            continue

    return calls


def extract_final_response(response: str) -> str:
    """Extract text response, removing tool call and thinking artifacts."""
    # Remove tool call blocks
    cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", response, flags=re.DOTALL)
    # Remove thinking blocks (Qwen3 hybrid reasoning)
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL)
    return cleaned.strip()


def format_tool_results(results: list[ToolResult]) -> str:
    """Format tool results for injection into conversation."""
    return "\n".join(
        f"<tool_response>\n{json.dumps({'name': r.tool_name, 'result': r.result})}\n</tool_response>"
        for r in results
    )


def extract_thinking(response: str) -> str | None:
    """Extract thinking content from LLM response."""
    match = re.search(r"<think>(.*?)</think>", response, re.DOTALL)
    return match.group(1).strip() if match else None


# --- Model Size Enum ---


from enum import Enum


class ModelSize(Enum):
    """Available model sizes mapped to MLX model IDs."""

    SMALL = "mlx-community/Qwen2.5-7B-Instruct-4bit"  # ~5GB
    MEDIUM = "mlx-community/Qwen2.5-14B-Instruct-4bit"  # ~10GB
    LARGE = "mlx-community/Qwen3-32B-4bit"  # ~18GB


# --- Qwen Model Singleton ---


class QwenModel:
    """
    Singleton wrapper around MLX-LM Qwen model.

    Loads model lazily on first inference request.
    """

    _instance: QwenModel | None = None

    def __init__(self, model_size: ModelSize = ModelSize.LARGE) -> None:
        self._model_size = model_size
        self._model: Any = None
        self._tokenizer: Any = None

    @classmethod
    def get_instance(cls, model_size: ModelSize = ModelSize.LARGE) -> QwenModel:
        """Get or create singleton instance."""
        if cls._instance is None or cls._instance._model_size != model_size:
            cls._instance = cls(model_size)
        return cls._instance

    def _ensure_loaded(self) -> tuple[Any, Any]:
        """Lazy load model and tokenizer."""
        if self._model is None or self._tokenizer is None:
            from mlx_lm import load

            print(f"Loading {self._model_size.value}...")
            result = load(self._model_size.value)
            self._model = result[0]
            self._tokenizer = result[1]
            print("Model loaded.")
        return self._model, self._tokenizer

    def generate(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
    ) -> str:
        """Generate response from messages."""
        model, tokenizer = self._ensure_loaded()

        prompt: str = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        import mlx_lm

        generate_fn = getattr(mlx_lm, "generate")
        response: str = generate_fn(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            verbose=False,
        )
        return response

    @property
    def is_loaded(self) -> bool:
        """Check if model is currently loaded."""
        return self._model is not None


# --- Chat Service ---


class ChatService:
    """
    Orchestrates chat conversations with tool execution.

    Features:
    - Profile-based configuration
    - Multi-round tool execution loop
    - Streaming-ready architecture
    """

    def __init__(
        self,
        model: QwenModel,
        registry: ToolRegistry,
    ) -> None:
        self._model = model
        self._registry = registry

    def chat(
        self,
        user_message: str,
        profile_name: str = "general",
        conversation_history: list[ChatMessage] | None = None,
        verbose: bool = False,
    ) -> ChatResponse:
        """
        Process a chat message with the specified agent profile (sync version).
        """
        profile = get_profile(profile_name)
        if profile is None:
            return ChatResponse(
                content=f"Unknown profile: {profile_name}",
                tool_calls=(),
                tool_results=(),
                rounds_used=0,
                finished=True,
            )

        system_prompt = build_system_prompt(profile)

        conversation: list[ChatMessage] = list(conversation_history or [])
        conversation.append(ChatMessage("user", user_message))

        all_tool_calls: list[ToolCall] = []
        all_tool_results: list[ToolResult] = []
        response: str = ""

        for round_num in range(profile.max_tool_rounds):
            messages = self._build_messages(system_prompt, conversation)

            if verbose:
                print(f"\n⏳ Round {round_num + 1} - Generating...")

            response = self._model.generate(messages, max_tokens=profile.max_tokens)

            if verbose:
                preview = response[:500] + "..." if len(response) > 500 else response
                print(f"✅ Round {round_num + 1} - Response:\n{'-' * 40}\n{preview}\n{'-' * 40}")

            tool_calls = parse_tool_calls(response)

            if not tool_calls:
                final_content = extract_final_response(response)

                if (
                    "<think>" in response
                    and len(final_content) < 50
                    and round_num < 3
                    and profile.tools
                ):
                    if verbose:
                        print("🔄 Model thinking without acting, nudging...")
                    conversation.append(ChatMessage("assistant", response))
                    conversation.append(
                        ChatMessage("user", "Now use your tools to help answer the question.")
                    )
                    continue

                return ChatResponse(
                    content=final_content,
                    tool_calls=tuple(all_tool_calls),
                    tool_results=tuple(all_tool_results),
                    rounds_used=round_num + 1,
                    finished=True,
                )

            if verbose:
                print(f"🔧 Found {len(tool_calls)} tool call(s):")
                for tc in tool_calls:
                    print(f"   - {tc.name}({tc.arguments})")

            round_results: list[ToolResult] = []
            for tc in tool_calls:
                result = self._registry.execute(tc.name, tc.arguments)
                round_results.append(ToolResult(tc.name, result))
                all_tool_calls.append(tc)
                all_tool_results.append(round_results[-1])

            if verbose:
                print("📦 Tool results:")
                for tr in round_results:
                    preview = tr.result[:200]
                    print(f"   - {tr.tool_name}: {preview}")

            conversation.append(ChatMessage("assistant", response))
            conversation.append(ChatMessage("user", format_tool_results(round_results)))

        return ChatResponse(
            content=extract_final_response(response),
            tool_calls=tuple(all_tool_calls),
            tool_results=tuple(all_tool_results),
            rounds_used=profile.max_tool_rounds,
            finished=False,
        )

    def _build_messages(
        self,
        system_prompt: str,
        conversation: list[ChatMessage],
    ) -> list[dict[str, str]]:
        """Convert conversation to model input format."""
        messages = [{"role": "system", "content": system_prompt}]
        for msg in conversation:
            messages.append({"role": msg.role, "content": msg.content})
        return messages

    async def chat_async(
        self,
        user_message: str,
        profile_name: str = "general",
        conversation_history: list[ChatMessage] | None = None,
        verbose: bool = False,
        on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> ChatResponse:
        """
        Process a chat message with the specified agent profile (async version).

        Supports async tools and runs model generation in a thread pool.
        """
        profile = get_profile(profile_name)
        if profile is None:
            return ChatResponse(
                content=f"Unknown profile: {profile_name}",
                tool_calls=(),
                tool_results=(),
                rounds_used=0,
                finished=True,
            )

        system_prompt = build_system_prompt(profile)
        max_rounds = profile.max_tool_rounds

        async def emit(event: dict[str, Any]) -> None:
            if on_event is not None:
                await on_event(event)

        conversation: list[ChatMessage] = list(conversation_history or [])
        conversation.append(ChatMessage("user", user_message))

        all_tool_calls: list[ToolCall] = []
        all_tool_results: list[ToolResult] = []
        response: str = ""

        for round_num in range(max_rounds):
            await emit({
                "type": "round_start",
                "round": round_num + 1,
                "max_rounds": max_rounds,
            })

            messages = self._build_messages(system_prompt, conversation)

            if verbose:
                print(f"\n⏳ Round {round_num + 1} - Generating...")

            await emit({
                "type": "generating",
                "round": round_num + 1,
                "max_rounds": max_rounds,
            })

            response = await asyncio.to_thread(
                self._model.generate, messages, profile.max_tokens
            )

            if verbose:
                preview = response[:500] + "..." if len(response) > 500 else response
                print(f"✅ Round {round_num + 1} - Response:\n{'-' * 40}\n{preview}\n{'-' * 40}")

            thinking = extract_thinking(response)
            if thinking:
                await emit({
                    "type": "thinking",
                    "content": thinking[:2000],
                    "round": round_num + 1,
                    "max_rounds": max_rounds,
                })

            tool_calls = parse_tool_calls(response)

            if not tool_calls:
                final_content = extract_final_response(response)

                if (
                    "<think>" in response
                    and len(final_content) < 50
                    and round_num < 3
                    and profile.tools
                ):
                    if verbose:
                        print("🔄 Model thinking without acting, nudging...")
                    conversation.append(ChatMessage("assistant", response))
                    conversation.append(
                        ChatMessage("user", "Now use your tools to help answer the question.")
                    )
                    continue

                return ChatResponse(
                    content=final_content,
                    tool_calls=tuple(all_tool_calls),
                    tool_results=tuple(all_tool_results),
                    rounds_used=round_num + 1,
                    finished=True,
                )

            if verbose:
                print(f"🔧 Found {len(tool_calls)} tool call(s):")
                for tc in tool_calls:
                    print(f"   - {tc.name}({tc.arguments})")

            round_results: list[ToolResult] = []
            for tc in tool_calls:
                truncated_args = _truncate_args(tc.arguments)
                await emit({
                    "type": "tool_start",
                    "tool_name": tc.name,
                    "tool_args": truncated_args,
                    "round": round_num + 1,
                    "max_rounds": max_rounds,
                })

                result = await self._registry.execute_async(tc.name, tc.arguments)
                round_results.append(ToolResult(tc.name, result))
                all_tool_calls.append(tc)
                all_tool_results.append(round_results[-1])

                await emit({
                    "type": "tool_end",
                    "tool_name": tc.name,
                    "tool_result": _truncate_result(result),
                    "round": round_num + 1,
                    "max_rounds": max_rounds,
                })

            if verbose:
                print("📦 Tool results:")
                for tr in round_results:
                    preview = tr.result[:200]
                    print(f"   - {tr.tool_name}: {preview}")

            conversation.append(ChatMessage("assistant", response))
            conversation.append(ChatMessage("user", format_tool_results(round_results)))

        return ChatResponse(
            content=extract_final_response(response),
            tool_calls=tuple(all_tool_calls),
            tool_results=tuple(all_tool_results),
            rounds_used=profile.max_tool_rounds,
            finished=False,
        )


def _truncate_args(args: dict[str, Any], max_len: int = 200) -> dict[str, Any]:
    """Truncate large argument values for SSE streaming."""
    truncated: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            if key == 'code':
                truncated[key] = value
            elif len(value) > max_len:
                truncated[key] = value[:max_len] + "..."
            else:
                truncated[key] = value
        else:
            truncated[key] = value
    return truncated


def _truncate_result(result: str, max_len: int = 500) -> str:
    """Truncate tool result for SSE streaming."""
    if len(result) > max_len:
        return result[:max_len] + "..."
    return result


# --- Factory Functions ---


def create_chat_service(model_size: ModelSize = ModelSize.LARGE) -> ChatService:
    """Create a chat service with the specified model size."""
    model = QwenModel.get_instance(model_size)
    registry = get_registry()
    return ChatService(model, registry)


# --- Standalone Test ---

if __name__ == "__main__":
    import sys

    model_size = ModelSize.LARGE
    if len(sys.argv) > 1:
        size_map = {
            "small": ModelSize.SMALL,
            "medium": ModelSize.MEDIUM,
            "large": ModelSize.LARGE,
        }
        model_size = size_map.get(sys.argv[1], ModelSize.LARGE)

    service = create_chat_service(model_size)

    print("Chat Service Test")
    print("=" * 40)

    response = service.chat("What is 2 + 2?", profile_name="general", verbose=True)
    print(f"\nFinal response: {response.content}")
    print(f"Rounds used: {response.rounds_used}")
