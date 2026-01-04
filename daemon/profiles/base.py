"""
Base types for the profile system.

A Profile bundles:
- System prompt (the agent's persona/instructions)
- Tools (imported from daemon.tools)
- Settings (max rounds, tokens, etc.)
- Auxiliary algorithms (optional context augmentation)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from daemon.tools import Tool


# Type for auxiliary context algorithms
# Takes current context dict, returns augmented context dict
ContextAugmenter = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class Profile:
    """
    Immutable agent profile configuration.
    
    Profiles define a specific "persona" with:
    - System prompt: Instructions and capabilities
    - Tools: Imported from daemon.tools modules
    - Settings: Inference parameters
    - Augmenters: Optional deterministic context augmentation
    """
    name: str
    system_prompt: str
    tools: tuple[Tool, ...]
    max_tool_rounds: int = 8
    max_tokens: int = 4096
    temperature: float = 0.7
    
    # Optional context augmenters - pure functions that deterministically
    # augment the context before sending to the LLM
    context_augmenters: tuple[ContextAugmenter, ...] = field(default=())

    @property
    def tool_names(self) -> tuple[str, ...]:
        """Get names of all tools in this profile."""
        return tuple(t.name for t in self.tools)

    def augment_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Apply all context augmenters in sequence.
        
        This allows profiles to deterministically add information to the
        context before it's sent to the LLM (e.g., adding current time,
        recent activity summaries, etc.)
        """
        result = context.copy()
        for augmenter in self.context_augmenters:
            result = augmenter(result)
        return result
