"""
Tests for OCR tool.

Tests both the tool directly and via the API endpoint.
Uses a Magic: The Gathering card image as test fixture.
"""

import json
import logging
from pathlib import Path

import httpx
import pytest

# Configure logging for test output
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Helper Functions ---


def _check_vision_framework_available() -> bool:
    """Check if macOS Vision framework is available via pyobjc."""
    try:
        __import__("Vision")
        return True
    except ImportError:
        return False


def _check_daemon_has_ocr() -> bool:
    """Check if running daemon has ocr_document tool registered."""
    try:
        response = httpx.get("http://127.0.0.1:5997/v1/tools", timeout=5.0)
        if response.status_code == 200:
            tools = response.json()
            return any(t["name"] == "ocr_document" for t in tools)
        return False
    except Exception:
        return False


# --- Test Constants ---


# Test image URL - Geosurge MTG card
TEST_IMAGE_URL = (
    "https://cards.scryfall.io/large/front/1/1/118b7aa3-bb05-4691-978e-51486435bf05.jpg"
)

# Expected text fragments in OCR output (flexible matching)
EXPECTED_FRAGMENTS = [
    "Geosurge",
    "Sorcery",
    "artifact",
    "creature",
    "spells",
    "mountains",
    "Koth",
]

# More specific expected content (at least some should match)
EXPECTED_CONTENT_OPTIONS = [
    "mana",  # "Add ... to your mana pool" or "Spend this mana"
    "cast",  # "only to cast artifact or creature spells"
    "corrupted",  # flavor text
    "fire",  # "lend me their fire"
    "Hammer",  # "Koth of the Hammer"
    "Igor",  # artist: Igor Kieryluk
]


# --- Fixtures ---


@pytest.fixture
def test_image_path(tmp_path: Path) -> Path:
    """Download test image to temp directory."""
    import urllib.request

    image_path = tmp_path / "geosurge.jpg"
    urllib.request.urlretrieve(TEST_IMAGE_URL, str(image_path))
    return image_path


class TestOCRToolDirect:
    """Direct tests for the OCR tool function."""

    @pytest.mark.skipif(
        not _check_vision_framework_available(),
        reason="Vision framework not available",
    )
    def test_ocr_image_basic(self, test_image_path: Path) -> None:
        """Test OCR on a real image returns expected content."""
        from daemon.tools.ocr.ocr_document import TOOL as ocr_tool

        logger.info(f"Running OCR on test image: {test_image_path}")
        result_json = ocr_tool.execute(file_path=str(test_image_path))
        result = json.loads(result_json)  # type: ignore[arg-type]

        logger.info(f"OCR status: {result.get('status')}")
        logger.info(f"OCR char_count: {result.get('char_count')}")
        logger.info(
            f"OCR full text:\n{'-'*60}\n{result.get('text', 'NO TEXT')}\n{'-'*60}"
        )

        assert result["status"] == "success", f"OCR failed: {result}"
        assert result["type"] == "image"
        assert "text" in result
        assert result["char_count"] > 0

        text = result["text"].lower()

        # Check that key card elements are recognized
        for frag in EXPECTED_FRAGMENTS:
            if frag.lower() in text:
                logger.info(f"  ✓ Found: '{frag}'")
            else:
                logger.warning(f"  ✗ Missing: '{frag}'")

        matched = sum(1 for frag in EXPECTED_FRAGMENTS if frag.lower() in text)
        assert matched >= 4, (
            f"Expected at least 4 of {EXPECTED_FRAGMENTS} in text, got {matched}. "
            f"Text:\n{text}"
        )

    def test_ocr_file_not_found(self) -> None:
        """Test OCR returns error for missing file."""
        from daemon.tools.ocr.ocr_document import TOOL as ocr_tool

        result_json = ocr_tool.execute(file_path="/nonexistent/path/to/file.png")
        result = json.loads(result_json)  # type: ignore[arg-type]

        assert result["status"] == "error"
        assert "not found" in result["error"].lower()

    def test_ocr_unsupported_format(self, tmp_path: Path) -> None:
        """Test OCR returns error for unsupported file type."""
        from daemon.tools.ocr.ocr_document import TOOL as ocr_tool

        # Create a fake file with unsupported extension
        fake_file = tmp_path / "document.xyz"
        fake_file.write_text("fake content")

        result_json = ocr_tool.execute(file_path=str(fake_file))
        result = json.loads(result_json)  # type: ignore[arg-type]

        assert result["status"] == "error"
        assert "unsupported" in result["error"].lower()


class TestOCRToolAPI:
    """E2E API tests for the OCR tool endpoint."""

    @pytest.fixture
    def api_client(self) -> httpx.Client:
        """Create HTTP client for API tests."""
        return httpx.Client(base_url="http://127.0.0.1:5997", timeout=120.0)

    @pytest.mark.skipif(
        not _check_daemon_has_ocr(),
        reason="Daemon not running or OCR tool not registered",
    )
    def test_ocr_tool_listed(self, api_client: httpx.Client) -> None:
        """Test that ocr_document tool is listed in available tools."""
        response = api_client.get("/v1/tools")
        assert response.status_code == 200

        tools = response.json()
        tool_names = [t["name"] for t in tools]
        assert "ocr_document" in tool_names

    @pytest.mark.skipif(
        not _check_daemon_has_ocr(),
        reason="Daemon not running or OCR tool not registered",
    )
    def test_ocr_tool_spec(self, api_client: httpx.Client) -> None:
        """Test that ocr_document tool spec is correct."""
        response = api_client.get("/v1/tools/ocr_document")
        assert response.status_code == 200

        spec = response.json()
        assert spec["name"] == "ocr_document"
        assert "PDF" in spec["description"] or "image" in spec["description"]
        assert "file_path" in spec["parameters"]["properties"]

    @pytest.mark.skipif(
        not _check_daemon_has_ocr() or not _check_vision_framework_available(),
        reason="Daemon without OCR tool or Vision framework not available",
    )
    def test_ocr_invoke_image(
        self, api_client: httpx.Client, test_image_path: Path
    ) -> None:
        """E2E test: invoke OCR tool via API on test image."""
        logger.info(f"E2E OCR test on: {test_image_path}")
        response = api_client.post(
            "/v1/tools/ocr_document/invoke",
            json={"arguments": {"file_path": str(test_image_path)}},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["tool_name"] == "ocr_document"
        logger.info(f"OCR latency: {data['latency_ms']:.1f}ms")

        result = data["result"]
        logger.info(f"OCR status: {result.get('status')}")
        logger.info(f"OCR text:\n{'-'*60}\n{result.get('text', 'NO TEXT')}\n{'-'*60}")

        assert result["status"] == "success", f"OCR failed: {result}"
        assert result["type"] == "image"

        text = result["text"].lower()

        # Verify key content was extracted
        assert "geosurge" in text, f"'Geosurge' not found in OCR output:\n{text}"
        assert "sorcery" in text, f"'Sorcery' not found in OCR output:\n{text}"

        # Check for mana-related content (flexible - may not capture {R} symbols)
        has_mana_context = any(word in text for word in ["mana", "cast", "spend"])
        assert has_mana_context, f"No mana-related content in OCR output:\n{text}"

    @pytest.mark.skipif(
        not _check_daemon_has_ocr(),
        reason="Daemon not running or OCR tool not registered",
    )
    def test_ocr_invoke_missing_file(self, api_client: httpx.Client) -> None:
        """Test API returns proper error for missing file."""
        response = api_client.post(
            "/v1/tools/ocr_document/invoke",
            json={"arguments": {"file_path": "/nonexistent/file.png"}},
        )
        assert response.status_code == 200  # Tool errors are returned in result

        data = response.json()
        result = data["result"]
        assert result["status"] == "error"
        assert "not found" in result["error"].lower()


class TestOCRChatIntegration:
    """Test OCR tool via chat interface."""

    @pytest.fixture
    def api_client(self) -> httpx.Client:
        """Create HTTP client for API tests."""
        return httpx.Client(base_url="http://127.0.0.1:5997", timeout=300.0)

    @pytest.mark.skipif(
        not _check_daemon_has_ocr() or not _check_vision_framework_available(),
        reason="Daemon without OCR tool or Vision framework not available",
    )
    def test_chat_uses_ocr_tool(
        self, api_client: httpx.Client, test_image_path: Path
    ) -> None:
        """Test that chat can use OCR tool when asked to read an image."""
        # Create a session with general profile (has OCR)
        response = api_client.post(
            "/v1/sessions",
            json={"profile_name": "general"},
        )
        assert response.status_code == 200
        session = response.json()
        session_id = session["id"]

        try:
            # Ask to OCR the image
            response = api_client.post(
                f"/v1/sessions/{session_id}/chat",
                json={
                    "message": f"Please use the OCR tool to read the text from this image: {test_image_path}",
                    "model_size": "large",
                },
            )
            assert response.status_code == 200

            data = response.json()
            chat_response = data["response"]

            # Check that OCR tool was called
            tool_names = [tc["name"] for tc in chat_response["tool_calls"]]
            assert (
                "ocr_document" in tool_names
            ), f"OCR tool not called. Tools used: {tool_names}"

            # Check response mentions the card
            content = chat_response["content"].lower()
            assert "geosurge" in content or any(
                "geosurge" in str(tr["result"]).lower()
                for tr in chat_response["tool_results"]
            ), "Geosurge not found in response or tool results"

        finally:
            # Cleanup session
            api_client.delete(f"/v1/sessions/{session_id}")
