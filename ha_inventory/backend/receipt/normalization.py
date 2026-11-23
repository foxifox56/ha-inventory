"""Shared normalization for receipt matching and duplicate fingerprints."""

from __future__ import annotations

import re
import unicodedata


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").casefold().replace("ß", "ss"))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", value))
