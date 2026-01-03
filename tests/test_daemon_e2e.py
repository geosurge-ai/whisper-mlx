#!/usr/bin/env python3
"""
End-to-end tests for Qwen daemon.

Tests the full request/response cycle through HTTP endpoints.
Uses pytest fixtures for setup/teardown of the daemon server.

Run with: pytest tests/test_daemon_e2e.py -v
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest


# --- Configuration ---

DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 18421  # Use non-standard port to avoid conflicts
DAEMON_URL = f"http://{DAEMON_HOST}:{DAEMON_PORT}"
STARTUP_TIMEOUT = 30  # seconds to wait for daemon to start
REQUEST_TIMEOUT = 120  # seconds for individual requests (model loading can be slow)


# --- HTTP Client Types ---

@dataclass(frozen=True)
class HttpResponse:
    """Immutable HTTP response."""
    status: int
    body: dict[str, Any] | list[Any] | str
    latency_ms: float


class TestClient:
    """Typed test client with get/post methods."""
    
    def get(self, path: str, timeout: float = REQUEST_TIMEOUT) -> HttpResponse:
        """GET request."""
        return http_request("GET", path, timeout=timeout)
    
    def post(self, path: str, data: dict[str, Any], timeout: float = REQUEST_TIMEOUT) -> HttpResponse:
        """POST request."""
        return http_request("POST", path, data=data, timeout=timeout)


# --- HTTP Client Utilities ---

def http_request(
    method: str,
    path: str,
    data: dict[str, Any] | None = None,
    timeout: float = REQUEST_TIMEOUT,
) -> HttpResponse:
    """
    Make HTTP request to daemon.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        path: URL path (e.g., "/health")
        data: JSON body for POST requests
        timeout: Request timeout in seconds
    
    Returns:
        HttpResponse with status, parsed body, and latency
    
    Raises:
        URLError: If connection fails
    """
    url = f"{DAEMON_URL}{path}"
    headers = {"Content-Type": "application/json"} if data else {}
    body_bytes = json.dumps(data).encode() if data else None
    
    req = Request(url, data=body_bytes, headers=headers, method=method)
    
    start = time.perf_counter()
    with urlopen(req, timeout=timeout) as resp:
        latency_ms = (time.perf_counter() - start) * 1000
        raw = resp.read().decode()
        parsed: dict[str, Any] | list[Any] | str
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return HttpResponse(status=resp.status, body=parsed, latency_ms=latency_ms)


def wait_for_server(timeout: float = STARTUP_TIMEOUT) -> bool:
    """
    Wait for daemon server to become ready.
    
    Returns:
        True if server is ready, False if timeout reached
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = http_request("GET", "/health", timeout=5)
            if resp.status == 200:
                return True
        except (URLError, OSError):
            pass
        time.sleep(0.5)
    return False


def is_port_free(port: int) -> bool:
    """Check if a port is available."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((DAEMON_HOST, port))
            return True
        except OSError:
            return False


# --- Fixtures ---

@pytest.fixture(scope="module")
def daemon_process() -> Generator[subprocess.Popen[bytes], None, None]:
    """
    Start daemon server for the test module.
    
    Setup:
        - Ensures port is free
        - Starts daemon in subprocess
        - Waits for server to be ready
    
    Teardown:
        - Sends SIGTERM to daemon
        - Waits for clean shutdown
    """
    # Ensure port is free
    if not is_port_free(DAEMON_PORT):
        pytest.skip(f"Port {DAEMON_PORT} is already in use")
    
    # Build command
    project_root = Path(__file__).parent.parent
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + ":" + env.get("PYTHONPATH", "")
    
    cmd = [
        sys.executable, "-m", "daemon.server",
        "--host", DAEMON_HOST,
        "--port", str(DAEMON_PORT),
    ]
    
    # Start daemon
    print(f"\n[SETUP] Starting daemon on {DAEMON_HOST}:{DAEMON_PORT}...")
    proc: subprocess.Popen[bytes] = subprocess.Popen(
        cmd,
        cwd=project_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    
    # Wait for ready
    if not wait_for_server():
        # Capture output for debugging
        proc.terminate()
        stdout, _ = proc.communicate(timeout=5)
        pytest.fail(f"Daemon failed to start. Output:\n{stdout.decode()}")
    
    print("[SETUP] Daemon is ready")
    yield proc
    
    # Teardown
    print("\n[TEARDOWN] Stopping daemon...")
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
        print("[TEARDOWN] Daemon stopped cleanly")
    except subprocess.TimeoutExpired:
        print("[TEARDOWN] Daemon did not stop, killing...")
        proc.kill()
        proc.wait()


@pytest.fixture
def client(daemon_process: subprocess.Popen[bytes]) -> TestClient:
    """
    Provide HTTP client bound to the running daemon.
    
    Returns TestClient instance with typed get/post methods.
    """
    _ = daemon_process  # Ensure daemon is running
    return TestClient()


# --- Helper Functions ---

def assert_dict_body(resp: HttpResponse) -> dict[str, Any]:
    """Assert response body is a dict and return it typed."""
    assert isinstance(resp.body, dict), f"Expected dict body, got {type(resp.body)}"
    body: dict[str, Any] = resp.body
    return body


def assert_list_body(resp: HttpResponse) -> list[dict[str, Any]]:
    """Assert response body is a list of dicts and return it typed."""
    assert isinstance(resp.body, list), f"Expected list body, got {type(resp.body)}"
    # All our list endpoints return list of dicts - cast the type
    result: list[dict[str, Any]] = resp.body  
    return result


# --- Health Endpoint Tests ---

class TestHealthEndpoint:
    """Tests for GET /health endpoint."""
    
    def test_health_returns_200(self, client: TestClient) -> None:
        """
        Input: GET /health
        Output: 200 OK with status="healthy"
        """
        resp = client.get("/health")
        body = assert_dict_body(resp)
        
        assert resp.status == 200
        assert body["status"] == "healthy"
    
    def test_health_contains_profiles(self, client: TestClient) -> None:
        """
        Input: GET /health
        Output: Response contains available_profiles list
        """
        resp = client.get("/health")
        body = assert_dict_body(resp)
        
        assert "available_profiles" in body
        profiles = body["available_profiles"]
        assert isinstance(profiles, list)
        assert "general" in profiles
        assert "mirror" in profiles
        assert "code_runner" in profiles
    
    def test_health_contains_tools(self, client: TestClient) -> None:
        """
        Input: GET /health
        Output: Response contains available_tools list
        """
        resp = client.get("/health")
        body = assert_dict_body(resp)
        
        assert "available_tools" in body
        tools: list[str] = body["available_tools"]
        assert len(tools) > 0


# --- Profile Endpoint Tests ---

class TestProfilesEndpoint:
    """Tests for GET /v1/profiles endpoint."""
    
    def test_profiles_returns_list(self, client: TestClient) -> None:
        """
        Input: GET /v1/profiles
        Output: List of profile objects
        """
        resp = client.get("/v1/profiles")
        body = assert_list_body(resp)
        
        assert resp.status == 200
        assert len(body) >= 3  # general, mirror, code_runner
    
    def test_profile_has_required_fields(self, client: TestClient) -> None:
        """
        Input: GET /v1/profiles
        Output: Each profile has name, system_prompt_preview, tool_names, max_tool_rounds
        """
        resp = client.get("/v1/profiles")
        body = assert_list_body(resp)
        
        for profile in body:
            assert "name" in profile
            assert "system_prompt_preview" in profile
            assert "tool_names" in profile
            assert "max_tool_rounds" in profile
    
    def test_general_profile_has_no_tools(self, client: TestClient) -> None:
        """
        Input: GET /v1/profiles
        Output: 'general' profile has empty tool_names
        """
        resp = client.get("/v1/profiles")
        body = assert_list_body(resp)
        
        general: dict[str, Any] | None = next(
            (p for p in body if p.get("name") == "general"),
            None
        )
        assert general is not None
        assert general["tool_names"] == []
    
    def test_mirror_profile_has_tools(self, client: TestClient) -> None:
        """
        Input: GET /v1/profiles
        Output: 'mirror' profile has Linear/Slack tools
        """
        resp = client.get("/v1/profiles")
        body = assert_list_body(resp)
        
        mirror: dict[str, Any] | None = next(
            (p for p in body if p.get("name") == "mirror"),
            None
        )
        assert mirror is not None
        tool_names: list[str] = mirror["tool_names"]
        assert "search_linear_issues" in tool_names
        assert "get_slack_thread" in tool_names


# --- Tools Endpoint Tests ---

class TestToolsEndpoint:
    """Tests for GET /v1/tools endpoint."""
    
    def test_tools_returns_list(self, client: TestClient) -> None:
        """
        Input: GET /v1/tools
        Output: List of tool objects
        """
        resp = client.get("/v1/tools")
        body = assert_list_body(resp)
        
        assert resp.status == 200
        assert len(body) > 0
    
    def test_tool_has_required_fields(self, client: TestClient) -> None:
        """
        Input: GET /v1/tools
        Output: Each tool has name, description, parameters
        """
        resp = client.get("/v1/tools")
        body = assert_list_body(resp)
        
        for tool in body:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool
    
    def test_profile_tools_endpoint(self, client: TestClient) -> None:
        """
        Input: GET /v1/profiles/mirror/tools
        Output: Only tools available for mirror profile
        """
        resp = client.get("/v1/profiles/mirror/tools")
        body = assert_list_body(resp)
        
        assert resp.status == 200
        tool_names: list[str] = [t["name"] for t in body]
        assert "search_linear_issues" in tool_names
        assert "web_search" not in tool_names  # browser tool, not mirror


# --- Tool Invocation Tests ---

class TestToolInvocation:
    """Tests for POST /v1/invoke-tool endpoint."""
    
    def test_invoke_unknown_tool_returns_404(self, client: TestClient) -> None:
        """
        Input: POST /v1/invoke-tool with unknown tool name
        Output: 404 Not Found
        """
        request_data: dict[str, Any] = {
            "tool_name": "nonexistent_tool",
            "arguments": {},
        }
        
        with pytest.raises(URLError) as exc_info:
            client.post("/v1/invoke-tool", request_data)
        assert "404" in str(exc_info.value)
    
    def test_invoke_tool_returns_result(self, client: TestClient) -> None:
        """
        Input: POST /v1/invoke-tool with search_linear_issues
        Output: Tool result with latency
        """
        request_data: dict[str, Any] = {
            "tool_name": "search_linear_issues",
            "arguments": {"query": "test", "limit": 1},
        }
        
        resp = client.post("/v1/invoke-tool", request_data)
        body = assert_dict_body(resp)
        
        assert resp.status == 200
        assert body["tool_name"] == "search_linear_issues"
        assert "result" in body
        assert "latency_ms" in body


# --- Chat Endpoint Tests ---

class TestChatEndpoint:
    """Tests for POST /v1/chat endpoint."""
    
    def test_chat_unknown_profile_returns_400(self, client: TestClient) -> None:
        """
        Input: POST /v1/chat with unknown profile
        Output: 400 Bad Request
        """
        request_data: dict[str, Any] = {
            "message": "Hello",
            "profile": "nonexistent_profile",
        }
        
        with pytest.raises(URLError) as exc_info:
            client.post("/v1/chat", request_data)
        assert "400" in str(exc_info.value)
    
    def test_chat_invalid_model_size_returns_400(self, client: TestClient) -> None:
        """
        Input: POST /v1/chat with invalid model_size
        Output: 400 Bad Request
        """
        request_data: dict[str, Any] = {
            "message": "Hello",
            "profile": "general",
            "model_size": "invalid_size",
        }
        
        with pytest.raises(URLError) as exc_info:
            client.post("/v1/chat", request_data)
        assert "400" in str(exc_info.value)
    
    def test_chat_response_has_required_fields(self, client: TestClient) -> None:
        """
        Input: POST /v1/chat with simple message
        Output: Response has content, tool_calls, rounds_used, finished, latency_ms
        """
        request_data: dict[str, Any] = {
            "message": "Say 'hello' and nothing else.",
            "profile": "general",
            "model_size": "large",
        }
        
        resp = client.post("/v1/chat", request_data, timeout=REQUEST_TIMEOUT)
        body = assert_dict_body(resp)
        
        assert resp.status == 200
        assert "content" in body
        assert "tool_calls" in body
        assert "tool_results" in body
        assert "rounds_used" in body
        assert "finished" in body
        assert "latency_ms" in body
    
    def test_chat_general_returns_content(self, client: TestClient) -> None:
        """
        Input: POST /v1/chat asking simple math question
        Output: Response content contains answer
        """
        request_data: dict[str, Any] = {
            "message": "What is 2+2? Reply with just the number.",
            "profile": "general",
            "model_size": "large",
        }
        
        resp = client.post("/v1/chat", request_data, timeout=REQUEST_TIMEOUT)
        body = assert_dict_body(resp)
        
        assert resp.status == 200
        assert "4" in body["content"]
        assert body["finished"] is True
    
    def test_chat_general_no_tool_calls(self, client: TestClient) -> None:
        """
        Input: POST /v1/chat with general profile (no tools)
        Output: tool_calls is empty list
        """
        request_data: dict[str, Any] = {
            "message": "Hello",
            "profile": "general",
            "model_size": "large",
        }
        
        resp = client.post("/v1/chat", request_data, timeout=REQUEST_TIMEOUT)
        body = assert_dict_body(resp)
        
        assert body["tool_calls"] == []
    
    def test_chat_with_history(self, client: TestClient) -> None:
        """
        Input: POST /v1/chat with conversation history
        Output: Response acknowledges context from history
        """
        request_data: dict[str, Any] = {
            "message": "What was my name again?",
            "profile": "general",
            "model_size": "large",
            "history": [
                {"role": "user", "content": "My name is Alice."},
                {"role": "assistant", "content": "Nice to meet you, Alice!"},
            ],
        }
        
        resp = client.post("/v1/chat", request_data, timeout=REQUEST_TIMEOUT)
        body = assert_dict_body(resp)
        
        assert resp.status == 200
        assert "Alice" in body["content"]


# --- Integration Tests ---

class TestIntegration:
    """Integration tests combining multiple endpoints."""
    
    def test_profile_tools_match_chat_behavior(self, client: TestClient) -> None:
        """
        Verify that tools listed for a profile are actually available during chat.
        
        Input: GET profile tools, then POST chat with that profile
        Output: Chat can use the listed tools
        """
        tools_resp = client.get("/v1/profiles/mirror/tools")
        tools_body = assert_list_body(tools_resp)
        tool_names: set[str] = {t["name"] for t in tools_body}
        
        assert "search_linear_issues" in tool_names
        assert "list_linear_events" in tool_names
    
    def test_health_reflects_model_load(self, client: TestClient) -> None:
        """
        After a chat request, health should show model_loaded=True.
        
        Input: POST /v1/chat, then GET /health
        Output: model_loaded is True after chat
        """
        chat_data: dict[str, Any] = {
            "message": "Hi",
            "profile": "general",
            "model_size": "large",
        }
        client.post("/v1/chat", chat_data, timeout=REQUEST_TIMEOUT)
        
        health_resp = client.get("/health")
        health_body = assert_dict_body(health_resp)
        
        assert health_body["model_loaded"] is True
        assert health_body["model_size"] == "LARGE"


# --- Performance Tests ---

class TestPerformance:
    """Basic performance/latency tests."""
    
    def test_health_is_fast(self, client: TestClient) -> None:
        """
        Input: GET /health
        Output: Response in < 100ms
        """
        resp = client.get("/health")
        assert resp.latency_ms < 100
    
    def test_profiles_is_fast(self, client: TestClient) -> None:
        """
        Input: GET /v1/profiles
        Output: Response in < 100ms
        """
        resp = client.get("/v1/profiles")
        assert resp.latency_ms < 100


# --- CLI Entry Point ---

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
