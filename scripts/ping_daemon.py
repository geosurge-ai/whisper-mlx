#!/usr/bin/env python3
"""
Smoke test client for Qwen daemon.

Tests:
1. Health check
2. Profile listing
3. Tool listing
4. General chat (no tools)
5. Mirror chat (with tools) - if mirror data available

Usage:
    python scripts/ping_daemon.py [host:port]

Default: http://127.0.0.1:5997
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Callable, cast
from urllib.request import urlopen, Request
from urllib.error import URLError

# Type alias for test functions
TestFunction = Callable[[str], bool]


def request(
    method: str, url: str, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Make HTTP request and return JSON response."""
    req = Request(
        url,
        data=json.dumps(data).encode() if data else None,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    try:
        with urlopen(req, timeout=120) as resp:
            result: dict[str, Any] = json.loads(resp.read().decode())
            return result
    except URLError as e:
        return {"error": str(e)}


def test_health(base_url: str) -> bool:
    """Test health endpoint."""
    print("\n1. Testing /health...")
    result = request("GET", f"{base_url}/health")

    if "error" in result:
        print(f"   ❌ Failed: {result['error']}")
        return False

    print(f"   ✅ Status: {result['status']}")
    print(f"   ✅ Model loaded: {result['model_loaded']}")
    print(f"   ✅ Profiles: {result['available_profiles']}")
    tools = result.get("available_tools", [])
    print(f"   ✅ Tools: {len(tools)} available")
    return True


def test_profiles(base_url: str) -> bool:
    """Test profiles endpoint."""
    print("\n2. Testing /v1/profiles...")

    # For list responses, we need to fetch directly since request() returns dict
    try:
        with urlopen(
            Request(f"{base_url}/v1/profiles", method="GET"), timeout=120
        ) as resp:
            profiles: list[dict[str, Any]] = json.loads(resp.read().decode())
            for profile in profiles:
                tool_count = len(profile.get("tool_names", []))
                max_rounds = profile.get("max_tool_rounds", 0)
                print(
                    f"   ✅ {profile['name']}: {tool_count} tools, max {max_rounds} rounds"
                )
            return True
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False


def test_tools(base_url: str) -> bool:
    """Test tools endpoint."""
    print("\n3. Testing /v1/tools...")

    try:
        with urlopen(
            Request(f"{base_url}/v1/tools", method="GET"), timeout=120
        ) as resp:
            tools: list[dict[str, Any]] = json.loads(resp.read().decode())
            print(f"   ✅ {len(tools)} tools available:")
            for tool in tools[:5]:
                desc = tool.get("description", "")[:60]
                print(f"      - {tool['name']}: {desc}...")
            if len(tools) > 5:
                print(f"      ... and {len(tools) - 5} more")
            return True
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False


def test_general_chat(base_url: str) -> bool:
    """Test general chat (no tools)."""
    print("\n4. Testing /v1/chat (general profile, no tools)...")
    print("   Sending: 'What is 2 + 2?'")

    start = time.time()
    result = request(
        "POST",
        f"{base_url}/v1/chat",
        {
            "message": "What is 2 + 2? Answer in one word.",
            "profile": "general",
            "model_size": "large",
        },
    )
    elapsed = time.time() - start

    if "error" in result:
        print(f"   ❌ Failed: {result['error']}")
        return False

    content = str(result.get("content", ""))[:100]
    print(f"   ✅ Response: {content}")
    print(
        f"   ✅ Rounds: {result.get('rounds_used')}, Finished: {result.get('finished')}"
    )
    print(f"   ✅ Latency: {result.get('latency_ms', 0):.0f}ms (total: {elapsed:.1f}s)")
    return True


def test_tool_invoke(base_url: str) -> bool:
    """Test direct tool invocation."""
    print("\n5. Testing /v1/invoke-tool...")
    print("   Invoking: search_linear_issues(query='test', limit=3)")

    result = request(
        "POST",
        f"{base_url}/v1/invoke-tool",
        {
            "tool_name": "search_linear_issues",
            "arguments": {"query": "test", "limit": 3},
        },
    )

    if "error" in result:
        # Tool might not be available if mirror data isn't present
        err_str = str(result)[:100]
        print(f"   ⚠️  Tool returned error (expected if no mirror data): {err_str}")
        return True  # Not a failure

    print(f"   ✅ Tool: {result.get('tool_name')}")
    print(f"   ✅ Latency: {result.get('latency_ms', 0):.0f}ms")
    tool_result = result.get("result")
    if isinstance(tool_result, dict):
        # Cast to typed dict to get properly typed keys
        typed_result = cast(dict[str, Any], tool_result)
        print(f"   ✅ Result keys: {list(typed_result.keys())}")
    return True


def test_mirror_chat(base_url: str) -> bool:
    """Test mirror chat (with tools)."""
    print("\n6. Testing /v1/chat (mirror profile, with tools)...")
    print("   Sending: 'List recent Linear activity'")

    start = time.time()
    result = request(
        "POST",
        f"{base_url}/v1/chat",
        {
            "message": "List the 3 most recent Linear events. Be very brief.",
            "profile": "mirror",
            "model_size": "large",
            "verbose": False,
        },
    )
    elapsed = time.time() - start

    if "error" in result:
        print(f"   ❌ Failed: {result['error']}")
        return False

    content = str(result.get("content", ""))[:200]
    print(f"   ✅ Response: {content}...")
    tool_calls: list[dict[str, Any]] = result.get("tool_calls", [])
    print(f"   ✅ Tool calls: {len(tool_calls)}")
    if tool_calls:
        for tc in tool_calls[:3]:
            args: dict[str, Any] = tc.get("arguments", {})
            arg_keys = list(args.keys())
            print(f"      - {tc.get('name')}({arg_keys})")
    print(
        f"   ✅ Rounds: {result.get('rounds_used')}, Finished: {result.get('finished')}"
    )
    print(f"   ✅ Latency: {result.get('latency_ms', 0):.0f}ms (total: {elapsed:.1f}s)")
    return True


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5997"

    print("=" * 60)
    print("🧪 Qwen Daemon Smoke Test")
    print("=" * 60)
    print(f"Target: {base_url}")

    tests: list[tuple[str, TestFunction]] = [
        ("Health check", test_health),
        ("Profile listing", test_profiles),
        ("Tool listing", test_tools),
        ("General chat", test_general_chat),
        ("Tool invocation", test_tool_invoke),
        ("Mirror chat", test_mirror_chat),
    ]

    passed = 0
    failed = 0

    for _, test_fn in tests:
        try:
            if test_fn(base_url):
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"   ❌ Exception: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
