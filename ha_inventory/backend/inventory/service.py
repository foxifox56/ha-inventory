"""Validation and use cases for inventory operations."""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

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
        "brand": 120,
        "product_size": 80,
        "image_url": 2048,
        "image_license": 80,
        "data_source": 80,
        "source_url": 2048,
    }
    FACTS_ROOTS = (
        "openfoodfacts.org",
        "openbeautyfacts.org",
        "openpetfoodfacts.org",
        "openproductsfacts.org",
    )
    TRACKING_MODES = {"simple", "inventory", "exact"}
    SIMPLE_STATUSES = {"unknown", "present", "out_of_stock"}
    UPDATE_FIELDS = set(TEXT_LIMITS) | {
        "quantity",
        "minimum_quantity",
        "tracking_mode",
        "stock_status",
    }

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
        if field in {"image_url", "source_url"} and value:
            parsed = urlsplit(value)
            hostname = (parsed.hostname or "").lower().rstrip(".")
            try:
                port = parsed.port
            except ValueError:
                port = -1
            if field == "image_url":
                valid_host = any(
                    hostname == root or hostname.endswith("." + root)
                    for root in self.FACTS_ROOTS
                )
            else:
                # Source links are navigated by the user only; allow future
                # provider domains while rejecting non-HTTPS/credential URLs.
                valid_host = bool(hostname)
            if (
                parsed.scheme != "https"
                or not valid_host
                or parsed.username is not None
                or parsed.password is not None
                or port not in (None, 443)
            ):
                raise InventoryError(
                    "Bild- und Quellen-URLs müssen sichere Open-Facts-HTTPS-Adressen sein.",
                    field=field,
                )
        return value

    @staticmethod
    def _quantity(raw: Any, field: str) -> float | None:
        if raw is None or raw == "":
            return None
        if isinstance(raw, bool):
            raise InventoryError("Muss eine Zahl ab 0 sein.", field=field)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise InventoryError("Muss eine Zahl ab 0 sein.", field=field) from None
        if not math.isfinite(value) or value < 0:
            raise InventoryError("Muss eine Zahl ab 0 sein.", field=field)
        return value

    def _tracking_mode(self, raw: Any) -> str:
        if not isinstance(raw, str) or raw not in self.TRACKING_MODES:
            raise InventoryError("Ungültiger Bestandsmodus.", field="tracking_mode")
        return raw

    def _stock_values(
        self,
        payload: dict[str, Any],
        existing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current_mode = existing["tracking_mode"] if existing else "simple"
        mode = self._tracking_mode(payload.get("tracking_mode", current_mode))

        if mode == "simple":
            raw_quantity = payload.get("quantity")
            if raw_quantity not in (None, ""):
                raise InventoryError(
                    "Im Modus „Einfacher Vorrat“ wird keine Menge erfasst.",
                    field="quantity",
                )
            current_status = (
                existing["stock_status"]
                if existing and current_mode == "simple"
                else "unknown"
            )
            status = payload.get("stock_status", current_status)
            if not isinstance(status, str) or status not in self.SIMPLE_STATUSES:
                raise InventoryError(
                    "Wähle unbekannt, vorhanden oder nicht vorhanden.",
                    field="stock_status",
                )
            return {
                "tracking_mode": mode,
                "stock_status": status,
                "quantity": None,
            }

        if "quantity" in payload:
            quantity = self._quantity(payload["quantity"], "quantity")
        elif existing and current_mode != "simple":
            quantity = existing["quantity"]
        else:
            quantity = None
        status = "known" if quantity is not None else "unknown"
        supplied_status = payload.get("stock_status", status)
        if supplied_status != status:
            raise InventoryError(
                "Der Bestandsstatus ergibt sich aus der eingetragenen Menge.",
                field="stock_status",
            )
        return {
            "tracking_mode": mode,
            "stock_status": status,
            "quantity": quantity,
        }

    def list_items(
        self,
        search: str = "",
        category: str = "",
        location: str = "",
        stock_status: str = "",
    ) -> list[dict[str, Any]]:
        return self.repository.list_items(
            search=search.strip(),
            category=category.strip(),
            location=location.strip(),
            stock_status=stock_status.strip(),
        )

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
        values = self._create_values(payload)
        try:
            return self.repository.create(values)
        except sqlite3.IntegrityError as error:
            self._raise_create_integrity_error(error)

    def _create_values(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise InventoryError("Die Anfrage muss ein JSON-Objekt enthalten.")
        unknown = set(payload) - self.UPDATE_FIELDS
        if unknown:
            raise InventoryError(f"Unbekanntes Feld: {sorted(unknown)[0]}.")
        barcode = self._text(payload, "barcode") or None
        now = self._timestamp()
        stock = self._stock_values(payload)
        values = {
            "name": self._text(payload, "name", required=True),
            "barcode": barcode,
            "category": self._text(payload, "category", default="Sonstiges")
            or "Sonstiges",
            **stock,
            "unit": self._text(payload, "unit", default="Stück") or "Stück",
            "location": self._text(payload, "location"),
            "minimum_quantity": self._quantity(
                payload.get("minimum_quantity", 0), "minimum_quantity"
            )
            or 0,
            "notes": self._text(payload, "notes"),
            "brand": self._text(payload, "brand"),
            "product_size": self._text(payload, "product_size"),
            "image_url": self._text(payload, "image_url"),
            "image_license": self._text(payload, "image_license"),
            "data_source": self._text(payload, "data_source"),
            "source_url": self._text(payload, "source_url"),
            "created_at": now,
            "updated_at": now,
        }
        return values

    def create_in_transaction(
        self, connection: sqlite3.Connection, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Create an item on the caller's transaction for atomic bulk imports."""
        values = self._create_values(payload)
        columns = list(values)
        try:
            cursor = connection.execute(
                f"INSERT INTO inventory_items ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                [values[column] for column in columns],
            )
            row = connection.execute(
                "SELECT * FROM inventory_items WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(row)
        except sqlite3.IntegrityError as error:
            self._raise_create_integrity_error(error)

    @staticmethod
    def _raise_create_integrity_error(error: sqlite3.IntegrityError) -> None:
        if "barcode" in str(error).lower():
            raise InventoryError(
                "Dieser Barcode ist bereits einem Artikel zugeordnet.",
                status_code=409,
                field="barcode",
            ) from error
        raise error

    def update(self, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise InventoryError("Die Anfrage muss ein JSON-Objekt enthalten.")
        unknown = set(payload) - self.UPDATE_FIELDS
        if unknown:
            raise InventoryError(f"Unbekanntes Feld: {sorted(unknown)[0]}.")
        if not payload:
            raise InventoryError("Keine Änderungen angegeben.")
        existing = self.repository.get(item_id)
        if existing is None:
            raise InventoryError("Artikel nicht gefunden.", status_code=404)
        if "quantity" in payload:
            requested_quantity = self._quantity(payload["quantity"], "quantity")
            if requested_quantity != existing["quantity"]:
                raise InventoryError(
                    "Mengen dürfen nur über eine Bestandsbuchung geändert werden.",
                    status_code=409,
                    field="quantity",
                )
        if (
            payload.get("tracking_mode") == "simple"
            and existing["tracking_mode"] in {"inventory", "exact"}
            and existing["quantity"] is not None
        ):
            raise InventoryError(
                "Ein erfasster Zahlenbestand kann nicht durch einen Modellwechsel verworfen werden.",
                status_code=409,
                field="tracking_mode",
            )
        stock_fields = {"tracking_mode", "stock_status", "quantity"}
        if stock_fields.intersection(payload):
            values: dict[str, Any] = self._stock_values(payload, existing)
        else:
            values = {}
        for field in payload:
            if field in {"tracking_mode", "stock_status", "quantity"}:
                continue
            if field in self.TEXT_LIMITS:
                value = self._text(
                    payload, field, required=(field == "name")
                )
                values[field] = (value or None) if field == "barcode" else value
            else:
                values[field] = self._quantity(payload[field], field)
                if values[field] is None:
                    raise InventoryError("Muss eine Zahl ab 0 sein.", field=field)
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
        try:
            if not self.repository.delete(item_id):
                raise InventoryError("Artikel nicht gefunden.", status_code=404)
        except sqlite3.IntegrityError as error:
            raise InventoryError(
                "Artikel mit Buchungsverlauf können nicht gelöscht werden.",
                status_code=409,
            ) from error
