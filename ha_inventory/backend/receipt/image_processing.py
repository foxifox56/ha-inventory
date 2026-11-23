"""Bounded, privacy-preserving image validation and OCR preparation."""

from __future__ import annotations

from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from ..errors import InventoryError


MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000
MAX_IMAGE_EDGE = 3000
SUPPORTED_MIME_TYPES = {"image/jpeg", "image/png"}


def prepare_image(image_bytes: bytes, content_type: str) -> bytes:
    """Validate and normalize a JPEG/PNG in memory; never write the source to disk."""
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise InventoryError("Wähle ein Kassenbonbild aus.", field="image")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise InventoryError("Das Bild ist größer als 6 MiB. Bitte kleiner aufnehmen.", status_code=413, field="image")
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime not in SUPPORTED_MIME_TYPES:
        raise InventoryError("Bitte ein JPEG- oder PNG-Bild verwenden. HEIC kann Safari vorher in JPEG umwandeln.", field="image")
    if mime == "image/jpeg" and not image_bytes.startswith(b"\xff\xd8\xff"):
        raise InventoryError("Die Bilddaten passen nicht zum JPEG-Dateityp.", field="image")
    if mime == "image/png" and not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise InventoryError("Die Bilddaten passen nicht zum PNG-Dateityp.", field="image")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(BytesIO(image_bytes))
            if probe.format not in {"JPEG", "PNG"}:
                raise InventoryError("Nur JPEG- und PNG-Bilder werden unterstützt.", field="image")
            width, height = probe.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise InventoryError("Das Bild hat zu viele Pixel. Bitte eine kleinere Aufnahme verwenden.", status_code=413, field="image")
            probe.verify()

            image = Image.open(BytesIO(image_bytes))
            image.load()
            image = ImageOps.exif_transpose(image).convert("L")
            image = ImageOps.autocontrast(image, cutoff=1)
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="PNG", optimize=False)
            return output.getvalue()
    except InventoryError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise InventoryError("Das Bild ist beschädigt oder kann nicht gelesen werden. Bitte erneut aufnehmen.", field="image") from error
