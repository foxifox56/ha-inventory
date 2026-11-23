"""Local Tesseract adapter with bounded runtime and process concurrency."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import io
import os
import shutil
import subprocess
import threading

from ..errors import InventoryError
from .image_processing import prepare_image


@dataclass(frozen=True)
class OCRLine:
    text: str
    confidence: float


@dataclass(frozen=True)
class OCRResult:
    text: str
    lines: tuple[OCRLine, ...]
    languages: tuple[str, ...]
    engine: str = "tesseract"


class TesseractEngine:
    """Run local Tesseract without a shell, disk files, or unbounded waits."""

    def __init__(self, binary: str | None = None, timeout_seconds: float = 15.0):
        self.binary = binary or shutil.which("tesseract") or "tesseract"
        self.timeout_seconds = timeout_seconds
        self._languages: tuple[str, ...] | None = None
        self._language_lock = threading.Lock()
        self._process_slot = threading.BoundedSemaphore(1)

    def available_languages(self) -> tuple[str, ...]:
        if self._languages is not None:
            return self._languages
        with self._language_lock:
            if self._languages is not None:
                return self._languages
            try:
                result = subprocess.run(
                    [self.binary, "--list-langs"], capture_output=True, text=True,
                    timeout=3, check=False, env={**os.environ, "OMP_THREAD_LIMIT": "1"},
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise InventoryError("Die lokale OCR-Engine Tesseract ist nicht verfügbar.", status_code=503) from error
            if result.returncode != 0:
                raise InventoryError("Die lokale OCR-Engine konnte ihre Sprachdaten nicht laden.", status_code=503)
            found = set(result.stdout.splitlines()[1:])
            self._languages = tuple(language for language in ("deu", "eng") if language in found)
            if not self._languages:
                raise InventoryError("Tesseract hat keine deutsche oder englische Sprachdatei installiert.", status_code=503)
            return self._languages

    def recognize(self, image_bytes: bytes, content_type: str) -> OCRResult:
        prepared = prepare_image(image_bytes, content_type)
        languages = self.available_languages()
        if not self._process_slot.acquire(blocking=False):
            raise InventoryError("Die Belegerkennung ist gerade ausgelastet. Bitte gleich erneut versuchen.", status_code=429)
        try:
            language_arg = "+".join(languages)
            try:
                result = subprocess.run(
                    [self.binary, "stdin", "stdout", "--oem", "1", "--psm", "6", "-l", language_arg, "tsv"],
                    input=prepared, capture_output=True, timeout=self.timeout_seconds,
                    check=False, env={**os.environ, "OMP_THREAD_LIMIT": "1"},
                )
            except subprocess.TimeoutExpired as error:
                raise InventoryError("Die lokale Texterkennung hat zu lange gedauert. Bitte ein kleineres oder schärferes Bild verwenden.", status_code=504) from error
            except OSError as error:
                raise InventoryError("Die lokale OCR-Engine konnte nicht gestartet werden.", status_code=503) from error
            if result.returncode != 0:
                raise InventoryError("Der Kassenbon konnte lokal nicht gelesen werden. Bitte erneut aufnehmen.", status_code=422)
            lines = self._parse_tsv(result.stdout.decode("utf-8", errors="replace"))
            text = "\n".join(line.text for line in lines)
            return OCRResult(text=text, lines=tuple(lines), languages=languages)
        finally:
            self._process_slot.release()

    @staticmethod
    def _parse_tsv(tsv: str) -> list[OCRLine]:
        grouped: dict[tuple[str, str, str, str, str], list[tuple[int, str]]] = {}
        try:
            for row in csv.DictReader(io.StringIO(tsv), delimiter="\t"):
                if row.get("level") != "5":
                    continue
                text = (row.get("text") or "").strip()
                try:
                    confidence = int(float(row.get("conf", "-1")))
                except ValueError:
                    continue
                if not text or confidence < 0:
                    continue
                key = tuple(row.get(name, "") for name in ("page_num", "block_num", "par_num", "line_num"))
                grouped.setdefault(key, []).append((confidence, text))
        except csv.Error as error:
            raise InventoryError("Die OCR-Antwort war ungültig. Bitte erneut aufnehmen.", status_code=422) from error
        lines = []
        for words in grouped.values():
            text = " ".join(word for _, word in words).strip()
            confidence = sum(score for score, _ in words) / max(1, len(words)) / 100
            if text:
                lines.append(OCRLine(text=text[:500], confidence=max(0.0, min(1.0, confidence))))
        return lines
