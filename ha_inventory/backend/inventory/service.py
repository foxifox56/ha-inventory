"""Validation and use cases for inventory operations."""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..errors import InventoryError
from .repository import InventoryRepository


class InventoryService:
    TEXT_LIMITS = {
        "name": 160,
        "barcode": 64,
        "category": 80,
        "unit": 40,
        "location": 160,
        "notes": 1000,
    }
    UPDATE_FIELDS = set(TEXT_LIMITS) | {"quantity", "minimum_quantity"}

    def __init__(self, repository: InventoryRepository):
        self.repository = repository

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )

    def _text(
        self,
        payload: dict[str, Any],
        field: str,
        *,
        default: str = "",
        required: bool = False,
    ) -> str:
        raw = payload.get(field, default)
        if raw is None and field == "barcode":
            return ""
        if not isinstance(raw, str):
            raise InventoryError("Muss Text sein.", field=field)
        value = raw.strip()
        if required and not value:
            raise InventoryError("Bitte einen Namen eingeben.", field=field)
        if len(value) > self.TEXT_LIMITS[field]:
            raise InventoryError(
                f"Darf höchstens {self.TEXT_LIMITS[field]} Zeichen lang sein.",
                field=field,
            )
        return value

    @staticmethod
    def _quantity(payload: dict[str, Any], field: str, default: float) -> float:
        raw = payload.get(field, default)
        if isinstance(raw, bool):
            raise InventoryError("Muss eine Zahl ab 0 sein.", field=field)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise InventoryError("Muss eine Zahl ab 0 sein.", field=field) from None
        if not math.isfinite(value) or value < 0:
            raise InventoryError("Muss eine Zahl ab 0 sein.", field=field)
        return value

    def list_items(self, search: str = "", category: str = "") -> list[dict[str, Any]]:
        return self.repository.list_items(search=search.strip(), category=category.strip())

    def get(self, item_id: int) -> dict[str, Any]:
        item = self.repository.get(item_id)
        if item is None:
            raise InventoryError("Artikel nicht gefunden.", status_code=404)
        return item

    def get_by_barcode(self, barcode: str) -> dict[str, Any]:
        clean_barcode = barcode.strip()
        if not clean_barcode:
            raise InventoryError("Barcode darf nicht leer sein.", field="barcode")
        item = self.repository.get_by_barcode(clean_barcode)
        if item is None:
            raise InventoryError("Kein Artikel mit diesem Barcode gefunden.", status_code=404)
        return item

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise InventoryError("Die Anfrage muss ein JSON-Objekt enthalten.")
        unknown = set(payload) - self.UPDATE_FIELDS
        if unknown:
            raise InventoryError(f"Unbekanntes Feld: {sorted(unknown)[0]}.")
        barcode = self._text(payload, "barcode") or None
        now = self._timestamp()
        values = {
            "name": self._text(payload, "name", required=True),
            "barcode": barcode,
            "category": self._text(payload, "category", default="Sonstiges")
            or "Sonstiges",
            "quantity": self._quantity(payload, "quantity", 1),
            "unit": self._text(payload, "unit", default="Stück") or "Stück",
            "location": self._text(payload, "location"),
            "minimum_quantity": self._quantity(payload, "minimum_quantity", 0),
            "notes": self._text(payload, "notes"),
            "created_at": now,
            "updated_at": now,
        }
        try:
            return self.repository.create(values)
        except sqlite3.IntegrityError as error:
            if "barcode" in str(error).lower():
                raise InventoryError(
                    "Dieser Barcode ist bereits einem Artikel zugeordnet.",
                    status_code=409,
                    field="barcode",
                ) from error
            raise

    def update(self, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise InventoryError("Die Anfrage muss ein JSON-Objekt enthalten.")
        unknown = set(payload) - self.UPDATE_FIELDS
        if unknown:
            raise InventoryError(f"Unbekanntes Feld: {sorted(unknown)[0]}.")
        if not payload:
            raise InventoryError("Keine Änderungen angegeben.")
        values: dict[str, Any] = {}
        for field in payload:
            if field in self.TEXT_LIMITS:
                value = self._text(
                    payload, field, required=(field == "name")
                )
                values[field] = (value or None) if field == "barcode" else value
            else:
                values[field] = self._quantity(payload, field, 0)
        values["updated_at"] = self._timestamp()
        try:
            item = self.repository.update(item_id, values)
        except sqlite3.IntegrityError as error:
            if "barcode" in str(error).lower():
                raise InventoryError(
                    "Dieser Barcode ist bereits einem Artikel zugeordnet.",
                    status_code=409,
                    field="barcode",
                ) from error
            raise
        if item is None:
            raise InventoryError("Artikel nicht gefunden.", status_code=404)
        return item

    def delete(self, item_id: int) -> None:
        if not self.repository.delete(item_id):
            raise InventoryError("Artikel nicht gefunden.", status_code=404)
