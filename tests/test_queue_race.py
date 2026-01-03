#!/usr/bin/env python3
"""
Regression test for queue position race condition.

This test verifies that concurrent requests to the daemon get unique,
sequential queue positions. The race condition occurred when:
1. Request R1 calls add_to_queue() and gets position 0
2. R1 acquires the lock immediately (no wait)
3. R1's synchronous model generation runs to completion
4. R2 only then calls add_to_queue() - also gets position 0!

The fix adds a cooperative yield (await asyncio.sleep(0)) after
add_to_queue() to let all concurrent requests queue up before
any of them acquire the generation lock.

Run with: pytest tests/test_queue_race.py -v
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any

import httpx
import pytest


# --- Configuration ---

DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 15998  # Use different port from other tests
DAEMON_URL = f"http://{DAEMON_HOST}:{DAEMON_PORT}"
STARTUP_TIMEOUT = 60  # seconds to wait for daemon to start
REQUEST_TIMEOUT = 300  # seconds for requests (model loading + generation)


# --- Fixtures ---


def is_port_in_use(port: int) -> bool:
    """Check if port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((DAEMON_HOST, port)) == 0


def wait_for_daemon(timeout: float) -> bool:
    """Wait for daemon to respond to health checks."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(f"{DAEMON_URL}/health")
                if resp.status_code == 200:
                    return True
        except httpx.RequestError:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def daemon_process() -> Generator[subprocess.Popen[bytes], None, None]:
    """Start daemon for the test module."""
    if is_port_in_use(DAEMON_PORT):
        pytest.skip(f"Port {DAEMON_PORT} already in use")

    # Find project root
    project_root = Path(__file__).parent.parent
    venv_python = project_root / ".venv" / "bin" / "python"

    if not venv_python.exists():
        pytest.skip(f"Virtual environment not found: {venv_python}")

    # Mirror data directories
    home = Path.home()
    mirror_base = home / "Github" / "vibe-os"

    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(project_root),
        "VIRTUAL_ENV": str(project_root / ".venv"),
        "PATH": f"{project_root / '.venv' / 'bin'}:{env.get('PATH', '')}",
        "LINEAR_MIRROR_DIR": str(mirror_base / "linear_mirror"),
        "VIBEOS_SLACK_MIRROR_DIR": str(mirror_base / "slack_mirror"),
    })

    proc = subprocess.Popen(
        [
            str(venv_python),
            "-m",
            "daemon.server",
            "--host",
            DAEMON_HOST,
            "--port",
            str(DAEMON_PORT),
        ],
        cwd=project_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for startup
    if not wait_for_daemon(STARTUP_TIMEOUT):
        proc.terminate()
        proc.wait(timeout=5)
        stdout, stderr = proc.communicate(timeout=5)
        pytest.fail(
            f"Daemon failed to start.\nstdout: {stdout.decode()}\nstderr: {stderr.decode()}"
        )

    yield proc

    # Teardown
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# --- Test ---


@pytest.mark.asyncio
async def test_concurrent_requests_get_unique_queue_positions(
    daemon_process: subprocess.Popen[bytes],
) -> None:
    """
    Regression test: concurrent requests MUST get unique queue positions.

    This tests the fix for the race condition where all requests got position 0
    because there was no yield point between add_to_queue() and lock acquisition.
    """
    # Create N concurrent sessions and send chat requests
    N = 3  # Keep small to reduce test time, but enough to verify uniqueness

    # Use connection pool with multiple connections to ensure truly concurrent requests
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=10)
    async with httpx.AsyncClient(
        base_url=DAEMON_URL, timeout=REQUEST_TIMEOUT, limits=limits
    ) as client:
        # First, create N sessions
        session_ids: list[str] = []
        for i in range(N):
            resp = await client.post(
                "/v1/sessions",
                json={"profile_name": "general"},
            )
            assert resp.status_code == 200, f"Failed to create session {i}: {resp.text}"
            session_ids.append(resp.json()["id"])

        # Define the chat request coroutine
        async def send_chat(session_id: str, idx: int) -> dict[str, Any]:
            """Send a chat request and return the response."""
            resp = await client.post(
                f"/v1/sessions/{session_id}/chat",
                json={
                    "message": f"Hello from request {idx}. Reply with just 'Hi {idx}'.",
                    "model_size": "large",
                },
            )
            assert resp.status_code == 200, f"Chat failed for {session_id}: {resp.text}"
            return resp.json()

        # Create ALL tasks FIRST, then await them
        # This ensures all coroutines are scheduled before any runs
        tasks = [
            asyncio.create_task(send_chat(sid, i))
            for i, sid in enumerate(session_ids)
        ]
        
        # Small yield to ensure all tasks have started
        await asyncio.sleep(0.01)
        
        # Now await all results
        results = await asyncio.gather(*tasks)

        # Extract queue positions from responses
        positions = [r["queue_stats"]["queue_position"] for r in results]
        was_queued = [r["queue_stats"]["was_queued"] for r in results]
        queue_waits = [r["queue_stats"]["queue_wait_ms"] for r in results]

        # Log results for debugging
        print(f"\n[TEST] Queue positions: {positions}")
        print(f"[TEST] Was queued: {was_queued}")
        print(f"[TEST] Queue waits: {[f'{w:.1f}ms' for w in queue_waits]}")

        # THE KEY ASSERTION: positions must be unique (no duplicates)
        # This proves the race condition fix works - each request gets a distinct position
        assert len(set(positions)) == N, (
            f"Queue positions have duplicates! "
            f"Got {positions}, but all {N} should be unique"
        )

        # Find which request got the lowest position (first to arrive)
        min_pos = min(positions)
        max_pos = max(positions)
        first_request_idx = positions.index(min_pos)
        last_request_idx = positions.index(max_pos)
        
        # The request with lowest position should NOT have been queued (got lock first)
        assert not was_queued[first_request_idx], (
            f"Request with lowest position ({min_pos}) should not have been queued"
        )

        # At least one request should have been queued (waited for others)
        # Note: not ALL higher positions need to wait - if the first request finishes
        # quickly, the second might get the lock immediately. But the LAST request
        # should definitely have waited (the semaphore serializes them).
        assert any(was_queued), "No requests were queued - semaphore not working?"
        
        # The request with highest position should have waited (it arrived last,
        # so at least one request was ahead of it and generating)
        assert was_queued[last_request_idx], (
            f"Request at highest position ({max_pos}) should have been queued"
        )
        assert queue_waits[last_request_idx] > 100, (  # At least 100ms
            f"Request at highest position ({max_pos}) should have significant wait time, "
            f"got {queue_waits[last_request_idx]:.1f}ms"
        )

        print(f"\n[TEST] ✓ All {N} requests got unique positions: {positions}")
        print(f"[TEST] ✓ Request {last_request_idx} (position {max_pos}) waited {queue_waits[last_request_idx]:.1f}ms")
        print(f"[TEST] ✓ Semaphore correctly serialized concurrent requests")
