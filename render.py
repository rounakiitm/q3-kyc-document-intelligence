"""Render source documents (images / PDFs) into PNG bytes for the vision model."""
from __future__ import annotations

import io
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from config import PDF_RENDER_DPI


def render_document(path: Path) -> list[bytes]:
    """Return one PNG (bytes) per page. Images -> single page; PDFs -> rasterised.

    Long images are downscaled so the largest side stays within 2000px, which
    is comfortably inside the model's vision resolution while keeping small
    handwritten digits legible.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        doc = pdfium.PdfDocument(path)
        pages: list[bytes] = []
        for page in doc:
            bitmap = page.render(scale=PDF_RENDER_DPI / 72)
            img = bitmap.to_pil()
            pages.append(_to_png(img))
        doc.close()
        return pages

    img = Image.open(path)
    if suffix in {".jpg", ".jpeg"}:
        img = img.convert("RGB")
    return [_to_png(img)]


def _to_png(img: Image.Image) -> bytes:
    img = img.convert("RGB")
    largest = max(img.size)
    if largest > 2000:
        scale = 2000 / largest
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
