"""Bounded JPEG and PNG normalization for ephemeral camera media."""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from orbitmind.camera.contracts import (
    CAMERA_MAX_ENCODED_BYTES,
    CAMERA_MAX_IMAGE_HEIGHT,
    CAMERA_MAX_IMAGE_WIDTH,
    CameraFrameFacts,
    CameraMediaType,
)

JPEG_FORMAT = "JPEG"
PNG_FORMAT = "PNG"


class CameraMediaError(Exception):
    """One sanitized camera-media failure safe for an API response."""

    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True, repr=False)
class NormalizedCameraFrame:
    """Newly encoded bytes and authoritative facts for one accepted frame."""

    content: bytes
    facts: CameraFrameFacts
    extension: str


class CameraMediaNormalizer:
    """Decode only JPEG/PNG and create a fresh metadata-minimized raster."""

    def normalize(
        self,
        content: bytes,
        declared_media_type: CameraMediaType,
    ) -> NormalizedCameraFrame:
        if not content:
            raise CameraMediaError("image_decode_failed", 400)
        if len(content) > CAMERA_MAX_ENCODED_BYTES:
            raise CameraMediaError("image_too_large", 413)

        detected = _detect_media_type(content)
        if detected is None or detected is not declared_media_type:
            raise CameraMediaError("image_type_invalid", 415)

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                return self._normalize_detected(content, detected)
        except CameraMediaError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise CameraMediaError("image_dimensions_invalid", 400) from exc
        except (UnidentifiedImageError, OSError, SyntaxError, TypeError, ValueError) as exc:
            raise CameraMediaError("image_decode_failed", 400) from exc

    def _normalize_detected(
        self,
        content: bytes,
        media_type: CameraMediaType,
    ) -> NormalizedCameraFrame:
        expected_format = JPEG_FORMAT if media_type is CameraMediaType.JPEG else PNG_FORMAT
        with Image.open(BytesIO(content), formats=(expected_format,)) as source:
            if source.format != expected_format:
                raise CameraMediaError("image_type_invalid", 415)
            _require_dimensions(source.width, source.height)
            if getattr(source, "n_frames", 1) != 1:
                raise CameraMediaError("image_type_invalid", 415)
            source.seek(0)
            source.load()
            oriented = ImageOps.exif_transpose(source)
            try:
                _require_dimensions(oriented.width, oriented.height)
                normalized = _fresh_raster(oriented, media_type)
                try:
                    output = BytesIO()
                    if media_type is CameraMediaType.JPEG:
                        normalized.save(
                            output,
                            format=JPEG_FORMAT,
                            quality=90,
                            progressive=False,
                        )
                        extension = ".jpg"
                    else:
                        normalized.save(output, format=PNG_FORMAT)
                        extension = ".png"
                finally:
                    normalized.close()
            finally:
                if oriented is not source:
                    oriented.close()

        encoded = output.getvalue()
        if not encoded or len(encoded) > CAMERA_MAX_ENCODED_BYTES:
            raise CameraMediaError("image_too_large", 413)
        width, height = _verify_normalized(encoded, expected_format)
        facts = CameraFrameFacts(
            media_type=media_type,
            width=width,
            height=height,
            encoded_size=len(encoded),
            content_checksum=hashlib.sha256(encoded).hexdigest(),
        )
        return NormalizedCameraFrame(content=encoded, facts=facts, extension=extension)


def _detect_media_type(content: bytes) -> CameraMediaType | None:
    if content.startswith(b"\xff\xd8\xff"):
        return CameraMediaType.JPEG
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return CameraMediaType.PNG
    return None


def _require_dimensions(width: int, height: int) -> None:
    if not 1 <= width <= CAMERA_MAX_IMAGE_WIDTH or not 1 <= height <= CAMERA_MAX_IMAGE_HEIGHT:
        raise CameraMediaError("image_dimensions_invalid", 400)


def _fresh_raster(source: Image.Image, media_type: CameraMediaType) -> Image.Image:
    if media_type is CameraMediaType.JPEG:
        mode = "RGB"
    else:
        mode = "RGBA" if "A" in source.getbands() or "transparency" in source.info else "RGB"
    converted = source.convert(mode)
    try:
        fresh = Image.new(mode, converted.size)
        fresh.paste(converted)
        return fresh
    finally:
        converted.close()


def _verify_normalized(content: bytes, expected_format: str) -> tuple[int, int]:
    with Image.open(BytesIO(content), formats=(expected_format,)) as verified:
        if verified.format != expected_format or getattr(verified, "n_frames", 1) != 1:
            raise CameraMediaError("image_decode_failed", 400)
        verified.load()
        _require_dimensions(verified.width, verified.height)
        if verified.mode not in {"RGB", "RGBA"}:
            raise CameraMediaError("image_decode_failed", 400)
        return verified.width, verified.height
