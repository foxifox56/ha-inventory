"""Conservative line parser for REWE, Kaufland, and generic German receipts."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .merchants import detect_merchant
from .normalization import normalize_text
from .ocr import OCRLine


_EXCLUDED = re.compile(
    r"^(?:PFAND|LEERGUT|EINWEG|MEHRWEG|RABATT|GUTSCHEIN|COUPON|PAYBACK|"
    r"ZWISCHENSUMME|SUMME|GESAMT|TOTAL|ZU ZAHLEN|ZAHLBETRAG|GEGEBEN|"
    r"RUECKGELD|RÜCKGELD|EC(?:[- ]?KARTE)?|KREDITKARTE|VISA|MASTERCARD|BAR|"
    r"KARTE|TSE|KASSE|KASSENBON|REWE(?:\s+MARKT)?|KAUFLAND|FILIALE|BON(?:[- ]?NR|NUMMER)?|"
    r"BELEG(?:[- ]?NR|NUMMER)?|TRANS(?:AKTION)?(?:[- ]?ID|[- ]?NR)?|STORNO|RUECKGABE|RÜCKGABE)\b",
    re.IGNORECASE,
)
_MONEY = re.compile(r"(?<![\w])\d{1,5}[,.]\d{2}(?!\d)")
_DATE = re.compile(r"\b(\d{2}\.\d{2}\.\d{2,4})\b")
_TIME = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d\b")
_REFERENCE = re.compile(
    r"\b(?:BON|BELEG|TRANS(?:AKTION)?|RECEIPT)\s*(?:NR|NUMMER|ID|NO)?\s*[:#-]?\s*([A-Z0-9-]{4,})\b",
    re.IGNORECASE,
)
_MULTIPLIER_PREFIX = re.compile(r"^\s*(\d{1,3})\s*[x×*]\s*(.+)$", re.IGNORECASE)
_COUNT_PREFIX = re.compile(r"^\s*(\d{1,3})\s*(?:STK|STÜCK|STUECK|PCS)\.?\s+(.+)$", re.IGNORECASE)
_COUNT_SUFFIX = re.compile(r"^(.+?)\s+(\d{1,3})\s*(?:STK|STÜCK|STUECK|PCS)\b(.*)$", re.IGNORECASE)
_INLINE_MULTIPLIER = re.compile(
    r"^(.+?)\s+(\d{1,3})\s*[x×]\s*\d{1,5}[,.]\d{2}(?:\s+\d{1,5}[,.]\d{2})?.*$",
    re.IGNORECASE,
)
_STANDALONE_MULTIPLIER = re.compile(
    r"^\s*(\d{1,3})\s*[x×]\s*\d{1,5}[,.]\d{2}(?:\s+\d{1,5}[,.]\d{2})?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedReceipt:
    merchant: str
    lines: tuple[dict, ...]
    ignored_line_count: int
    receipt_date: str | None
    receipt_time: str | None
    total: str | None
    reference: str | None


def _clean_label(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" \t|:-")
    value = re.sub(r"\s+(?:[A-D])$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+\d{1,5}[,.]\d{2}\s+[A-D]$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+\d{1,5}[,.]\d{2}(?:\s+\d{1,5}[,.]\d{2})?$", "", value)
    value = re.sub(r"\s+\d{1,5}[,.]\d{2}\s*€?$", "", value)
    return value.strip(" \t|:-")[:160]


def parse_receipt(lines: list[OCRLine]) -> ParsedReceipt:
    full_text = "\n".join(line.text for line in lines)
    merchant = detect_merchant(full_text)
    date_match = _DATE.search(full_text)
    time_match = _TIME.search(full_text)
    total = None
    for line in lines:
        if re.match(r"^\s*(?:SUMME|GESAMT|TOTAL|ZU ZAHLEN|ZAHLBETRAG)\b", line.text, re.IGNORECASE):
            money = _MONEY.findall(line.text)
            if money:
                total = money[-1].replace(",", ".")
                break
    reference_match = _REFERENCE.search(full_text)

    parsed: list[dict] = []
    ignored = 0
    last_unpriced_index: int | None = None
    for index, ocr_line in enumerate(lines, start=1):
        raw = re.sub(r"\s+", " ", ocr_line.text).strip()
        if not raw:
            ignored += 1
            continue
        if _EXCLUDED.search(raw) or raw.startswith("-") or re.fullmatch(r"[\d\s.,€]+", raw):
            ignored += 1
            last_unpriced_index = None
            continue
        multiplier = _STANDALONE_MULTIPLIER.match(raw)
        if multiplier and last_unpriced_index is not None:
            quantity = int(multiplier.group(1))
            if 1 <= quantity <= 999:
                parsed[last_unpriced_index]["quantity"] = quantity
                parsed[last_unpriced_index]["quantity_source"] = "multiplier"
                parsed[last_unpriced_index]["requires_review"] = ocr_line.confidence < 0.55
                last_unpriced_index = None
                ignored += 1
                continue

        label = raw
        quantity: int | None = None
        quantity_source = "single"
        explicit_count = False

        match = _COUNT_PREFIX.match(label)
        if match:
            quantity, label, explicit_count = int(match.group(1)), match.group(2), True
            quantity_source = "count"
        else:
            match = _MULTIPLIER_PREFIX.match(label)
            if match:
                quantity, label, explicit_count = int(match.group(1)), match.group(2), True
                quantity_source = "multiplier"
            else:
                match = _COUNT_SUFFIX.match(label)
                if match:
                    label, quantity, explicit_count = match.group(1), int(match.group(2)), True
                    quantity_source = "count"
                else:
                    match = _INLINE_MULTIPLIER.match(label)
                    if match:
                        label, quantity, explicit_count = match.group(1), int(match.group(2)), True
                        quantity_source = "multiplier"

        label = _clean_label(label)
        normalized = normalize_text(label)
        if len(normalized) < 3 or not re.search(r"[a-zäöüß]{2}", label, re.IGNORECASE):
            ignored += 1
            last_unpriced_index = None
            continue

        has_price = bool(_MONEY.search(raw))
        if quantity is None:
            quantity = 1 if has_price else None
        if quantity is not None and not (1 <= quantity <= 999):
            quantity = None
        requires_review = (
            quantity is None or ocr_line.confidence < 0.65
            or (explicit_count and ocr_line.confidence < 0.72)
        )
        parsed.append({
            "line_id": index,
            "label": label,
            "quantity": quantity,
            "quantity_source": quantity_source if quantity is not None else "unknown",
            "confidence": round(max(0.0, min(1.0, ocr_line.confidence)), 3),
            "requires_review": requires_review,
            "item_id": None,
            "match_confidence": 0.0,
            "match_source": "none",
            "candidates": [],
        })
        last_unpriced_index = len(parsed) - 1 if not has_price else None

    # Merge repeated physical lines only when their normalized label matches.
    # The preview retains their source line IDs so the consolidation is auditable.
    merged: list[dict] = []
    positions: dict[str, int] = {}
    for row in parsed:
        key = normalize_text(row["label"])
        if key in positions:
            current = merged[positions[key]]
            if current["quantity"] is not None and row["quantity"] is not None:
                combined = current["quantity"] + row["quantity"]
                current["quantity"] = combined if combined <= 999 else None
            else:
                current["quantity"] = None
            current["line_ids"].append(row["line_id"])
            current["confidence"] = min(current["confidence"], row["confidence"])
            current["requires_review"] = current["requires_review"] or row["requires_review"]
        else:
            row["line_ids"] = [row["line_id"]]
            positions[key] = len(merged)
            merged.append(row)

    return ParsedReceipt(
        merchant=merchant,
        lines=tuple(merged),
        ignored_line_count=ignored,
        receipt_date=date_match.group(1) if date_match else None,
        receipt_time=time_match.group(0) if time_match else None,
        total=total,
        reference=reference_match.group(1).upper() if reference_match else None,
    )
