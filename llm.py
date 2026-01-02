#!/usr/bin/env python3
"""
Tool-calling LLM powered by Qwen3 on MLX.

Qwen3-32B-4bit is currently the most capable open-source tool-using LLM
that fits comfortably on M4 MacBook Pro (requires ~18GB unified memory).

For 16GB machines, use Qwen3-14B-4bit or Qwen2.5-14B-Instruct-4bit.
"""

from dataclasses import dataclass
from typing import Any, Callable
import json
import re

from mlx_lm import load, generate


# --- Configuration ---

@dataclass(frozen=True)
class ModelConfig:
    """Immutable model configuration."""
    model_id: str
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 0.9


# Available models by memory requirement
MODELS = {
    "large": ModelConfig("mlx-community/Qwen3-32B-4bit"),      # ~18GB, best capability
    "medium": ModelConfig("mlx-community/Qwen2.5-14B-Instruct-4bit"),  # ~10GB
    "small": ModelConfig("mlx-community/Qwen2.5-7B-Instruct-4bit"),    # ~5GB
}

DEFAULT_MODEL = "large"


# --- Tool Definition ---

@dataclass(frozen=True)
class Tool:
    """Immutable tool definition for function calling."""
    name: str
    description: str
    parameters: dict[str, Any]
    function: Callable[..., Any]

    def to_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema format for LLM."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


# --- Message Types ---

@dataclass(frozen=True)
class Message:
    """Base message in conversation."""
    role: str
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
    result: Any


# --- Core Functions (Pure) ---

def format_tools_prompt(tools: list[Tool]) -> str:
    """Format tools into system prompt section."""
    schemas = [tool.to_schema() for tool in tools]
    tools_json = "\n".join(json.dumps(s) for s in schemas)
    return f"""# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{tools_json}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{{"name": "<function-name>", "arguments": {{"<arg1>": "<value1>"}}}}
</tool_call>"""


def build_messages(
    system_prompt: str,
    conversation: list[Message],
    tool_results: list[ToolResult] | None = None,
) -> list[dict[str, str]]:
    """Build message list for tokenizer chat template."""
    messages = [{"role": "system", "content": system_prompt}]

    for msg in conversation:
        messages.append({"role": msg.role, "content": msg.content})

    if tool_results:
        # Tool results are sent as special user messages
        results_content = "\n".join(
            f"<tool_response>\n{json.dumps({'name': r.tool_name, 'result': r.result})}\n</tool_response>"
            for r in tool_results
        )
        messages.append({"role": "user", "content": results_content})

    return messages


def parse_tool_calls(response: str) -> list[ToolCall]:
    """Extract tool calls from LLM response."""
    pattern = r"<tool_call>\s*({.*?})\s*</tool_call>"
    matches = re.findall(pattern, response, re.DOTALL)

    calls = []
    for match in matches:
        try:
            data = json.loads(match)
            calls.append(ToolCall(
                name=data.get("name", ""),
                arguments=data.get("arguments", {}),
            ))
        except json.JSONDecodeError:
            continue

    return calls


def extract_final_response(response: str) -> str:
    """Extract text response, removing tool call artifacts."""
    # Remove tool call blocks
    cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", response, flags=re.DOTALL)
    # Remove thinking blocks (Qwen3 hybrid reasoning)
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL)
    return cleaned.strip()


# --- LLM Engine (Stateful) ---

class LLMEngine:
    """Tool-calling LLM engine using Qwen3 on MLX."""

    def __init__(self, model_size: str = DEFAULT_MODEL):
        config = MODELS.get(model_size, MODELS[DEFAULT_MODEL])
        self.config = config
        self._model = None
        self._tokenizer = None

    def _ensure_loaded(self) -> None:
        """Lazy load model and tokenizer."""
        if self._model is None:
            print(f"Loading {self.config.model_id}...")
            self._model, self._tokenizer = load(self.config.model_id)
            print("Model loaded.")

    def generate(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> str:
        """Generate response from messages."""
        self._ensure_loaded()

        prompt = self._tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        response = generate(
            self._model,
            self._tokenizer,
            prompt=prompt,
            max_tokens=max_tokens or self.config.max_tokens,
            verbose=False,
        )

        return response


# --- High-Level API ---

class ToolCallingAgent:
    """
    Agent that can use tools to accomplish tasks.

    Example:
        >>> def get_weather(city: str) -> str:
        ...     return f"Weather in {city}: Sunny, 22°C"
        ...
        >>> weather_tool = Tool(
        ...     name="get_weather",
        ...     description="Get current weather for a city",
        ...     parameters={
        ...         "type": "object",
        ...         "properties": {"city": {"type": "string", "description": "City name"}},
        ...         "required": ["city"],
        ...     },
        ...     function=get_weather,
        ... )
        >>> agent = ToolCallingAgent(tools=[weather_tool])
        >>> response = agent.run("What's the weather in Tokyo?")
    """

    def __init__(
        self,
        tools: list[Tool],
        model_size: str = DEFAULT_MODEL,
        system_prompt: str = "You are a helpful assistant.",
        max_tool_rounds: int = 5,
    ):
        self.tools = {t.name: t for t in tools}
        self.engine = LLMEngine(model_size)
        self.base_system_prompt = system_prompt
        self.max_tool_rounds = max_tool_rounds

    def _build_system_prompt(self) -> str:
        """Combine base prompt with tools definition."""
        tools_prompt = format_tools_prompt(list(self.tools.values()))
        return f"{self.base_system_prompt}\n\n{tools_prompt}"

    def _execute_tool(self, call: ToolCall) -> ToolResult:
        """Execute a single tool call."""
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(call.name, {"error": f"Unknown tool: {call.name}"})

        try:
            result = tool.function(**call.arguments)
            return ToolResult(call.name, result)
        except Exception as e:
            return ToolResult(call.name, {"error": str(e)})

    def run(self, user_input: str, verbose: bool = True) -> str:
        """
        Process user input, executing tools as needed.

        Returns the final text response after all tool interactions.
        """
        conversation = [Message("user", user_input)]
        system_prompt = self._build_system_prompt()

        for round_num in range(self.max_tool_rounds):
            messages = build_messages(system_prompt, conversation)
            response = self.engine.generate(messages)

            if verbose:
                print(f"\n🔄 Round {round_num + 1} - LLM Response:")
                print("-" * 40)
                print(response[:500] + "..." if len(response) > 500 else response)
                print("-" * 40)

            # Check for tool calls
            tool_calls = parse_tool_calls(response)
            if not tool_calls:
                if verbose:
                    print("📭 No tool calls found, returning final response.")
                # No more tool calls, return final response
                return extract_final_response(response)

            if verbose:
                print(f"🔧 Found {len(tool_calls)} tool call(s):")
                for tc in tool_calls:
                    print(f"   - {tc.name}({tc.arguments})")

            # Execute tools and continue conversation
            tool_results = [self._execute_tool(call) for call in tool_calls]

            if verbose:
                print("📦 Tool results:")
                for tr in tool_results:
                    result_str = str(tr.result)[:200]
                    print(f"   - {tr.tool_name}: {result_str}")

            # Add assistant response with tool calls
            conversation.append(Message("assistant", response))

            # Add tool results as user message
            results_content = "\n".join(
                f"<tool_response>\n{json.dumps({'name': r.tool_name, 'result': r.result})}\n</tool_response>"
                for r in tool_results
            )
            conversation.append(Message("user", results_content))

        # Max rounds reached
        return extract_final_response(response)


# --- CLI Entry Point ---

def main():
    """Interactive CLI for testing the LLM."""
    import sys

    model_size = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    print(f"Initializing Qwen3 Tool-Calling LLM ({model_size})...")
    print("Type 'quit' to exit.\n")

    engine = LLMEngine(model_size)

    conversation = []
    system = "You are a helpful AI assistant."

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        if not user_input:
            continue

        conversation.append({"role": "user", "content": user_input})
        messages = [{"role": "system", "content": system}] + conversation

        print("\nAssistant: ", end="", flush=True)
        response = engine.generate(messages)
        print(response)
        print()

        conversation.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()
