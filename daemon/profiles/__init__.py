"""
Profiles package: Agent profile definitions.

Each profile is a module that imports tools and defines:
- System prompt
- Tool set (via imports from daemon.tools)
- Auxiliary algorithms for context augmentation

Profiles are pure configuration - no side effects.
"""

from .base import Profile
from .mirror import PROFILE as mirror
from .code_runner import PROFILE as code_runner
from .general import PROFILE as general

# All profiles exported from this package
ALL_PROFILES: dict[str, Profile] = {
    "mirror": mirror,
    "code_runner": code_runner,
    "general": general,
}


def get_profile(name: str) -> Profile | None:
    """Get a profile by name."""
    return ALL_PROFILES.get(name)


def list_profiles() -> list[str]:
    """List all available profile names."""
    return list(ALL_PROFILES.keys())


__all__ = [
    "Profile",
    "ALL_PROFILES",
    "get_profile",
    "list_profiles",
    "mirror",
    "code_runner",
    "general",
]
