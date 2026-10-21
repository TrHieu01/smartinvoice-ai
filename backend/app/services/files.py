from io import BytesIO

import pymupdf
from PIL import Image, UnidentifiedImageError

from backend.app.core.errors import AppError


def inspect_file(
    data: bytes, expected_mime: str, max_pages: int = 5, max_pixels: int = 20_000_000
) -> int:
    if not data:
        raise AppError("corrupt_file")
    if expected_mime == "application/pdf":
        if not data.startswith(b"%PDF-"):
            raise AppError("unsupported_media_type", 415)
        try:
            with pymupdf.open(stream=data, filetype="pdf") as document:
                if document.needs_pass:
                    raise AppError("encrypted_pdf")
                if not 1 <= document.page_count <= max_pages:
                    raise AppError("page_limit_exceeded")
                for page in document:
                    if (
                        page.rect.width <= 0
                        or page.rect.height <= 0
                        or page.rect.width * page.rect.height * (200 / 72) ** 2 > max_pixels
                    ):
                        raise AppError("image_too_large")
                return document.page_count
        except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
            raise AppError("corrupt_file") from exc
    try:
        with Image.open(BytesIO(data)) as image:
            actual = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(
                image.format
            )
            if actual != expected_mime:
                raise AppError("unsupported_media_type", 415)
            if image.width * image.height > max_pixels:
                raise AppError("image_too_large")
            if getattr(image, "n_frames", 1) != 1:
                raise AppError("animated_image_not_supported")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise AppError("corrupt_file") from exc
    return 1
