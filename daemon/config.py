"""
Legacy configuration module.

This module is DEPRECATED in favor of the new modular structure:
- daemon.tools: Tool definitions and registry
- daemon.profiles: Profile definitions

This file provides backwards compatibility re-exports.
"""

from __future__ import annotations

# Re-export from new locations for backwards compatibility
from .chat import ModelSize
from .tools import ToolSpec, get_registry
from .profiles import ALL_PROFILES, get_profile, Profile


# --- Legacy Types (Deprecated) ---

# AgentProfile is now Profile in daemon.profiles.base
AgentProfile = Profile


# --- Legacy Accessors (Deprecated) ---

AGENT_PROFILES = ALL_PROFILES


def get_tools_for_profile(profile_name: str) -> tuple[ToolSpec, ...]:
    """
    DEPRECATED: Use profile.tools directly.
    
    Get tool specs for a given agent profile.
    """
    profile = get_profile(profile_name)
    if profile is None:
        return ()
    return tuple(t.spec for t in profile.tools)


# Build ALL_TOOL_SPECS from registry
def _build_all_tool_specs() -> dict[str, ToolSpec]:
    registry = get_registry()
    return registry.get_all_specs()


# Lazy initialization to avoid circular imports
_ALL_TOOL_SPECS: dict[str, ToolSpec] | None = None


def _get_all_tool_specs() -> dict[str, ToolSpec]:
    global _ALL_TOOL_SPECS
    if _ALL_TOOL_SPECS is None:
        _ALL_TOOL_SPECS = _build_all_tool_specs()
    return _ALL_TOOL_SPECS


# This will be populated on first access
class _LazyToolSpecsDict(dict):
    """Lazy dict that loads tool specs on first access."""
    _loaded = False
    
    def _ensure_loaded(self):
        if not self._loaded:
            self.update(_get_all_tool_specs())
            self._loaded = True
    
    def __getitem__(self, key):
        self._ensure_loaded()
        return super().__getitem__(key)
    
    def __iter__(self):
        self._ensure_loaded()
        return super().__iter__()
    
    def __len__(self):
        self._ensure_loaded()
        return super().__len__()
    
    def keys(self):
        self._ensure_loaded()
        return super().keys()
    
    def values(self):
        self._ensure_loaded()
        return super().values()
    
    def items(self):
        self._ensure_loaded()
        return super().items()


ALL_TOOL_SPECS = _LazyToolSpecsDict()
