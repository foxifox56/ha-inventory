"""Merchant alias and conservative local catalog matching."""

from __future__ import annotations

from difflib import SequenceMatcher

from .normalization import normalize_text


def _tokens(value: str) -> set[str]:
    return set(normalize_text(value).split())


def _similarity(receipt_label: str, item: dict) -> float:
    label = normalize_text(receipt_label)
    catalog = normalize_text(" ".join(filter(None, (item.get("name"), item.get("brand"), item.get("product_size")))))
    if not label or not catalog:
        return 0.0
    if label == catalog:
        return 1.0
    label_tokens = _tokens(receipt_label)
    item_tokens = _tokens(" ".join(filter(None, (item.get("name"), item.get("brand"), item.get("product_size")))))
    token_score = len(label_tokens & item_tokens) / max(1, len(item_tokens))
    sequence_score = SequenceMatcher(None, label, catalog).ratio()
    score = 0.62 * sequence_score + 0.38 * token_score
    if item_tokens and item_tokens.issubset(label_tokens):
        score = max(score, 0.9)
    return min(1.0, score)


def match_lines(lines: list[dict], merchant: str, items: list[dict], aliases: dict[str, dict]) -> list[dict]:
    by_id = {item["id"]: item for item in items}
    for line in lines:
        normalized = normalize_text(line["label"])
        alias = aliases.get(normalized)
        if alias and alias["item_id"] in by_id:
            target = by_id[alias["item_id"]]
            line.update({
                "item_id": target["id"], "match_confidence": 1.0,
                "match_source": "merchant_alias", "matched_item_name": target["name"],
            })
            continue
        scored = sorted(
            ((_similarity(line["label"], item), item) for item in items),
            key=lambda entry: (entry[0], str(entry[1]["name"]).casefold()), reverse=True,
        )
        candidates = [
            {"item_id": item["id"], "name": item["name"], "confidence": round(score, 3)}
            for score, item in scored[:3] if score >= 0.28
        ]
        line["candidates"] = candidates
        best = scored[0] if scored else (0.0, None)
        second = scored[1][0] if len(scored) > 1 else 0.0
        if best[1] is not None and best[0] >= 0.82 and best[0] - second >= 0.08:
            line.update({
                "item_id": best[1]["id"], "match_confidence": round(best[0], 3),
                "match_source": "catalog_suggestion", "matched_item_name": best[1]["name"],
            })
        else:
            line["item_id"] = None
            line["match_confidence"] = round(best[0], 3) if best[1] is not None else 0.0
            line["match_source"] = "ambiguous" if candidates else "unmatched"
            line["matched_item_name"] = ""
    return lines
