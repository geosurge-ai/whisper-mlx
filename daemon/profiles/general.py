"""
General profile: Basic assistant without tools.

A minimal profile for general conversation without tool access.
"""

from .base import Profile


# --- System Prompt ---

SYSTEM_PROMPT = """You are a helpful AI assistant. You answer questions clearly and concisely."""


# --- Profile Definition ---

PROFILE = Profile(
    name="general",
    system_prompt=SYSTEM_PROMPT,
    tools=(),
    max_tool_rounds=1,
    max_tokens=4096,
)
