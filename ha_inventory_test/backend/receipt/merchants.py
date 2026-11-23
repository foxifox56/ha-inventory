"""Merchant classification for supported supermarket receipt layouts."""

from __future__ import annotations

import re


def detect_merchant(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").upper())
    if re.search(r"\bREWE\b", normalized):
        return "rewe"
    if re.search(r"\bKAUFLAND\b", normalized):
        return "kaufland"
    return "other"
