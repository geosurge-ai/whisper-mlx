"""
OCR Document tool.

Extract text from images and PDFs using macOS Vision framework.

Supports:
- Images: PNG, JPG, JPEG, WEBP, GIF, BMP, TIFF
- Documents: PDF (multi-page)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typing import Protocol

    class VNObservation(Protocol):
        def topCandidates_(self, count: int) -> list[Any]: ...

    class VNTextCandidate(Protocol):
        def string(self) -> str: ...

    class VNRecognizeTextRequest(Protocol):
        def setRecognitionLevel_(self, level: int) -> None: ...
        def setUsesLanguageCorrection_(self, flag: bool) -> None: ...
        def results(self) -> list[VNObservation] | None: ...

    class VNImageRequestHandler(Protocol):
        def performRequests_error_(
            self, requests: list[Any], error: Any
        ) -> tuple[bool, Any]: ...

from Cocoa import NSURL
import Vision

from ..base import tool

logger = logging.getLogger("qwen.ocr")

# Supported image formats
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif"}
PDF_EXTENSIONS = {".pdf"}


def _pdf_to_images(pdf_path: Path, dpi: int = 200) -> list[Path]:
    """
    Convert PDF pages to images using PyMuPDF.
    """
    import fitz  # PyMuPDF

    image_paths: list[Path] = []

    doc = fitz.open(pdf_path)
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            # Render at specified DPI
            zoom = dpi / 72  # 72 is default PDF DPI
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            # Save to temp file
            fd, temp_path_str = tempfile.mkstemp(suffix=f"_page{page_num + 1}.png")
            os.close(fd)  # Close fd, we'll write via pix.save
            temp_path = Path(temp_path_str)
            pix.save(str(temp_path))
            image_paths.append(temp_path)

            logger.debug(f"Converted PDF page {page_num + 1} to {temp_path}")
    finally:
        doc.close()

    return image_paths


def _ocr_image(image_path: Path) -> str:
    """
    Perform OCR on a single image using macOS Vision framework.
    """
    logger.info(f"OCR processing: {image_path}")

    # Create image URL
    image_url: Any = NSURL.fileURLWithPath_(str(image_path))

    # Create Vision request handler
    handler: Any = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
        image_url, None
    )

    # Create text recognition request
    request: Any = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)

    # Perform request
    success: bool
    error: Any
    success, error = handler.performRequests_error_([request], None)

    if not success:
        error_msg = str(error) if error else "Unknown Vision framework error"
        raise RuntimeError(f"Vision OCR failed: {error_msg}")

    # Extract text from results
    results: list[Any] | None = request.results()
    if not results:
        return ""

    text_blocks: list[str] = []
    for observation in results:
        candidates = observation.topCandidates_(1)
        if candidates:
            text_blocks.append(str(candidates[0].string()))

    text = "\n".join(text_blocks)
    logger.info(f"OCR extracted {len(text)} characters")

    return text


def _cleanup_temp_files(paths: list[Path]) -> None:
    """Remove temporary files."""
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file {path}: {e}")


@tool(
    name="ocr_document",
    description="""Extract text from images or PDF documents using macOS Vision framework.

Supports:
- Images: PNG, JPG, JPEG, WEBP, GIF, BMP, TIFF
- Documents: PDF (processes all pages)

Works well with:
- Printed documents and books
- Screenshots and UI captures
- Tables and structured layouts
- Multi-column documents

For PDFs, each page is processed separately and results are combined.""",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the image or PDF file to OCR",
            },
            "pages": {
                "type": "string",
                "description": "For PDFs: page range to process (e.g., '1-5', '1,3,5', 'all'). Default: 'all'",
            },
            "dpi": {
                "type": "integer",
                "description": "DPI for PDF rendering (higher = better quality, slower). Default: 200",
            },
        },
        "required": ["file_path"],
    },
)
def ocr_document(
    file_path: str,
    pages: str = "all",
    dpi: int = 200,
) -> str:
    """
    Extract text from an image or PDF document.

    Args:
        file_path: Path to the image or PDF file
        pages: For PDFs, which pages to process ('all', '1-5', '1,3,5')
        dpi: DPI for PDF rendering (default 200)

    Returns:
        JSON with extracted text and metadata
    """
    path = Path(file_path).expanduser().resolve()

    if not path.exists():
        return json.dumps(
            {
                "error": f"File not found: {file_path}",
                "status": "error",
            }
        )

    suffix = path.suffix.lower()

    # Validate file type
    if suffix not in IMAGE_EXTENSIONS and suffix not in PDF_EXTENSIONS:
        return json.dumps(
            {
                "error": f"Unsupported file type: {suffix}. Supported: {IMAGE_EXTENSIONS | PDF_EXTENSIONS}",
                "status": "error",
            }
        )

    temp_files: list[Path] = []

    try:
        if suffix in IMAGE_EXTENSIONS:
            # Single image OCR
            logger.info(f"OCR processing image: {path.name}")
            text = _ocr_image(path)

            logger.info(
                f"OCR result for {path.name}: {text[:200]}..."
                if len(text) > 200
                else f"OCR result for {path.name}: {text}"
            )

            return json.dumps(
                {
                    "status": "success",
                    "file": str(path),
                    "type": "image",
                    "text": text,
                    "char_count": len(text),
                }
            )

        else:
            # PDF OCR
            logger.info(f"OCR processing PDF: {path.name}")

            # Convert PDF to images
            image_paths = _pdf_to_images(path, dpi=dpi)
            temp_files.extend(image_paths)
            total_pages = len(image_paths)

            # Parse page range
            pages_to_process: list[int] = []
            if pages == "all":
                pages_to_process = list(range(total_pages))
            elif "-" in pages:
                start, end = pages.split("-")
                pages_to_process = list(
                    range(int(start) - 1, min(int(end), total_pages))
                )
            elif "," in pages:
                pages_to_process = [
                    int(p) - 1 for p in pages.split(",") if 0 < int(p) <= total_pages
                ]
            else:
                try:
                    page_num = int(pages)
                    if 0 < page_num <= total_pages:
                        pages_to_process = [page_num - 1]
                except ValueError:
                    pages_to_process = list(range(total_pages))

            # OCR each page
            page_results: list[dict[str, Any]] = []
            all_text: list[str] = []

            for idx in pages_to_process:
                if idx < len(image_paths):
                    logger.info(f"OCR processing page {idx + 1}/{total_pages}")
                    page_text = _ocr_image(image_paths[idx])
                    page_results.append(
                        {
                            "page": idx + 1,
                            "text": page_text,
                            "char_count": len(page_text),
                        }
                    )
                    all_text.append(f"--- Page {idx + 1} ---\n{page_text}")

            combined_text = "\n\n".join(all_text)

            logger.info(
                f"OCR result for {path.name}: {combined_text[:200]}..."
                if len(combined_text) > 200
                else f"OCR result for {path.name}: {combined_text}"
            )

            return json.dumps(
                {
                    "status": "success",
                    "file": str(path),
                    "type": "pdf",
                    "total_pages": total_pages,
                    "pages_processed": len(pages_to_process),
                    "text": combined_text,
                    "char_count": len(combined_text),
                    "page_details": page_results,
                }
            )

    except Exception as e:
        logger.exception(f"OCR failed for {path}")
        return json.dumps(
            {
                "error": f"OCR failed: {str(e)}",
                "status": "error",
            }
        )

    finally:
        _cleanup_temp_files(temp_files)


TOOL = ocr_document
