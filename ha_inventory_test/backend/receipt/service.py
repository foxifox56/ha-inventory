"""Privacy-preserving receipt recognition and atomic stock import use cases."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import uuid
from typing import Any

from ..database import Database
from ..errors import InventoryError
from ..inventory.movements import StockMovementService
from ..inventory.service import InventoryService
from .matching import match_lines
from .normalization import normalize_text
from .ocr import TesseractEngine
from .parsing import parse_receipt


class ReceiptService:
    MAX_LINES = 300
    MAX_QUANTITY = StockMovementService.MAX_SAFE_QUANTITY
    MERCHANTS = {"rewe", "kaufland", "other"}

    def __init__(
        self, database: Database, inventory: InventoryService,
        movements: StockMovementService, ocr: TesseractEngine | None = None,
    ):
        self.database = database
        self.inventory = inventory
        self.movements = movements
        self.ocr = ocr or TesseractEngine()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _request_hash(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _required_key(payload: dict[str, Any], field: str = "idempotency_key") -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120:
            raise InventoryError("Es fehlt ein gültiger Idempotenzschlüssel (maximal 120 Zeichen).", field=field)
        return value.strip()

    @classmethod
    def _quantity(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= cls.MAX_QUANTITY:
            raise InventoryError(
                "Die erkannte Menge muss eine ganze Zahl zwischen 1 und 9.007.199.254.740.991 sein.",
                field="quantity",
            )
        return value

    @staticmethod
    def _fingerprint(merchant: str, parsed) -> tuple[str, str]:
        if parsed.reference:
            material = f"{merchant}|reference|{parsed.reference}|{parsed.receipt_date or ''}|{parsed.receipt_time or ''}|{parsed.total or ''}"
            strength = "strong"
        elif parsed.receipt_date and parsed.receipt_time and parsed.total:
            material = f"{merchant}|date-time-total|{parsed.receipt_date}|{parsed.receipt_time}|{parsed.total}"
            strength = "strong"
        else:
            rows = "|".join(
                f"{normalize_text(line['label'])}:{line['quantity']}"
                for line in parsed.lines
            )
            material = f"{merchant}|weak|{rows}"
            strength = "weak"
        return hashlib.sha256(material.encode("utf-8")).hexdigest(), strength

    def recognize(self, image: bytes, content_type: str) -> dict[str, Any]:
        """Run local OCR, parse the preview, and store only hashes and receipt metadata."""
        result = self.ocr.recognize(image, content_type)
        parsed = parse_receipt(list(result.lines))
        if len(parsed.lines) > self.MAX_LINES:
            raise InventoryError("Auf dem Bon wurden zu viele Positionen erkannt. Bitte ein kleineres Bild verwenden.", status_code=422)
        receipt_id = str(uuid.uuid4())
        image_hash = hashlib.sha256(image).hexdigest()
        fingerprint, fingerprint_strength = self._fingerprint(parsed.merchant, parsed)
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            items = [dict(row) for row in connection.execute(
                "SELECT * FROM inventory_items ORDER BY id"
            ).fetchall()]
            aliases = {
                row["normalized_alias"]: dict(row)
                for row in connection.execute(
                    "SELECT * FROM receipt_product_aliases WHERE merchant = ?",
                    (parsed.merchant,),
                ).fetchall()
            }
            lines = match_lines([dict(line) for line in parsed.lines], parsed.merchant, items, aliases)
            duplicate_rows = connection.execute(
                """SELECT id, status, created_at, fingerprint_strength FROM receipt_imports
                   WHERE status IN ('imported', 'undone')
                     AND (image_sha256 = ? OR (merchant = ? AND receipt_fingerprint = ?))
                   ORDER BY created_at DESC LIMIT 5""",
                (image_hash, parsed.merchant, fingerprint),
            ).fetchall()
            connection.execute(
                """INSERT INTO receipt_imports (
                    id, merchant, image_sha256, receipt_fingerprint, fingerprint_strength,
                    line_count, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'recognized', ?)""",
                (receipt_id, parsed.merchant, image_hash, fingerprint, fingerprint_strength,
                 max((max(line["line_ids"]) for line in lines), default=0), self._now()),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return {
            "receipt_id": receipt_id,
            "merchant": parsed.merchant,
            "merchant_label": {"rewe": "REWE", "kaufland": "Kaufland", "other": "Unbekannt"}[parsed.merchant],
            "receipt_date": parsed.receipt_date,
            "receipt_time": parsed.receipt_time,
            "total": parsed.total,
            "fingerprint_strength": fingerprint_strength,
            "duplicate_warning": bool(duplicate_rows),
            "duplicates": [dict(row) for row in duplicate_rows],
            "lines": lines,
            "ignored_line_count": parsed.ignored_line_count,
            "ocr": {"engine": result.engine, "languages": list(result.languages)},
            "privacy": "Bild und vollständiger OCR-Text werden nicht gespeichert.",
        }

    def _load_receipt(self, connection, receipt_id: str):
        if not isinstance(receipt_id, str) or len(receipt_id) != 36:
            raise InventoryError("Kassenbon nicht gefunden.", status_code=404)
        row = connection.execute("SELECT * FROM receipt_imports WHERE id = ?", (receipt_id,)).fetchone()
        if row is None:
            raise InventoryError("Kassenbon nicht gefunden.", status_code=404)
        return dict(row)

    def _validate_rows(self, payload: dict[str, Any], line_count: int) -> list[dict[str, Any]]:
        if set(payload) - {"confirmed", "idempotency_key", "allow_duplicate", "rows"}:
            raise InventoryError("Die Anfrage enthält ein unbekanntes Feld.")
        if payload.get("confirmed") is not True:
            raise InventoryError("Bitte bestätige die geprüften Bonpositionen ausdrücklich.", field="confirmed")
        if "allow_duplicate" in payload and not isinstance(payload["allow_duplicate"], bool):
            raise InventoryError("Die Dubletten-Ausnahme muss ausdrücklich bestätigt werden.", field="allow_duplicate")
        rows = payload.get("rows")
        if not isinstance(rows, list) or not rows or len(rows) > self.MAX_LINES:
            raise InventoryError("Wähle mindestens eine gültige Bonposition.", field="rows")
        allowed_fields = {
            "line_ids", "label", "decision", "item_id", "quantity", "tracking_mode", "name",
            "barcode", "category", "location", "unit", "learn_alias", "replace_alias",
        }
        seen_line_ids: set[int] = set()
        cleaned = []
        for row in rows:
            if not isinstance(row, dict) or set(row) - allowed_fields:
                raise InventoryError("Eine Bonposition enthält ungültige Daten.", field="rows")
            line_ids = row.get("line_ids")
            if not isinstance(line_ids, list) or not line_ids:
                raise InventoryError("Jede Auswahl benötigt mindestens eine Bonzeile.", field="rows")
            normalized_ids = []
            for line_id in line_ids:
                if isinstance(line_id, bool) or not isinstance(line_id, int) or not 1 <= line_id <= line_count:
                    raise InventoryError("Die Bonzeile ist ungültig oder gehört nicht zu dieser Erkennung.", field="rows")
                if line_id in seen_line_ids:
                    raise InventoryError("Eine Bonzeile darf nur einmal übernommen werden.", field="rows")
                seen_line_ids.add(line_id)
                normalized_ids.append(line_id)
            decision = row.get("decision")
            if not isinstance(decision, str) or decision not in {"existing", "new", "skip"}:
                raise InventoryError("Wähle einen vorhandenen Artikel, einen neuen Artikel oder Überspringen.", field="decision")
            item = dict(row, line_ids=normalized_ids, decision=decision)
            label = row.get("label", "")
            if not isinstance(label, str) or len(label.strip()) > 160:
                raise InventoryError("Ungültiger erkannter Produktname.", field="label")
            item["label"] = label.strip()
            if decision != "skip":
                item["quantity"] = self._quantity(row.get("quantity"))
                for field, limit in (("name", 160), ("barcode", 64), ("category", 80), ("location", 160), ("unit", 40)):
                    value = row.get(field, "")
                    if not isinstance(value, str) or len(value.strip()) > limit:
                        raise InventoryError(f"Ungültiger Wert für {field}.", field=field)
                    item[field] = value.strip()
                item["learn_alias"] = row.get("learn_alias") is True
                item["replace_alias"] = row.get("replace_alias") is True
                if decision == "existing":
                    item_id = row.get("item_id")
                    if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
                        raise InventoryError("Wähle einen vorhandenen Lagerartikel.", field="item_id")
                    item["item_id"] = item_id
                else:
                    if not item["name"]:
                        raise InventoryError("Gib für einen neuen Artikel einen Namen ein.", field="name")
                    mode = row.get("tracking_mode")
                    if not isinstance(mode, str) or mode not in {"inventory", "exact"}:
                        raise InventoryError("Lege den Bestandsmodus für den neuen Artikel ausdrücklich fest.", field="tracking_mode")
                    item["tracking_mode"] = mode
            cleaned.append(item)
        return cleaned

    def _save_alias(self, connection, merchant: str, alias: str, item_id: int, replace: bool) -> None:
        normalized = normalize_text(alias)
        if len(normalized) < 3:
            raise InventoryError("Die erkannte Bezeichnung ist zu kurz, um sie als Zuordnung zu speichern.", field="learn_alias")
        existing = connection.execute(
            "SELECT item_id FROM receipt_product_aliases WHERE merchant = ? AND normalized_alias = ?",
            (merchant, normalized),
        ).fetchone()
        if existing and existing["item_id"] != item_id and not replace:
            raise InventoryError(
                "Diese REWE-/Kaufland-Bezeichnung ist bereits einem anderen Artikel zugeordnet.",
                status_code=409, field="learn_alias", code="receipt_alias_conflict",
            )
        now = self._now()
        connection.execute(
            """INSERT INTO receipt_product_aliases (
                merchant, normalized_alias, alias_text, item_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(merchant, normalized_alias) DO UPDATE SET
                alias_text = excluded.alias_text, item_id = excluded.item_id,
                updated_at = excluded.updated_at""",
            (merchant, normalized, alias.strip()[:160], item_id, now, now),
        )

    def import_receipt(self, receipt_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise InventoryError("Die Anfrage muss ein JSON-Objekt enthalten.")
        key = self._required_key(payload)
        request_hash = self._request_hash(payload)
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            receipt = self._load_receipt(connection, receipt_id)
            if receipt["status"] == "imported":
                if receipt["idempotency_key"] == key and receipt["request_hash"] == request_hash:
                    connection.commit()
                    return self._receipt_summary(connection, receipt_id, replayed=True)
                raise InventoryError("Dieser Kassenbon wurde bereits mit einer anderen Anfrage übernommen.", status_code=409, code="receipt_already_imported")
            if receipt["status"] != "recognized":
                raise InventoryError("Ein rückgängig gemachter Bon kann nicht erneut importiert werden.", status_code=409)
            key_owner = connection.execute(
                "SELECT id FROM receipt_imports WHERE idempotency_key = ? AND id != ?",
                (key, receipt_id),
            ).fetchone()
            if key_owner:
                raise InventoryError("Der Idempotenzschlüssel wurde bereits für einen anderen Bon verwendet.", status_code=409)
            rows = self._validate_rows(payload, receipt["line_count"])
            if not any(row["decision"] != "skip" for row in rows):
                raise InventoryError("Alle Bonpositionen sind übersprungen; es gibt nichts zu buchen.", field="rows")
            duplicates = connection.execute(
                """SELECT id FROM receipt_imports WHERE id != ? AND status IN ('imported', 'undone')
                   AND (image_sha256 = ? OR (merchant = ? AND receipt_fingerprint = ?)) LIMIT 1""",
                (receipt_id, receipt["image_sha256"], receipt["merchant"], receipt["receipt_fingerprint"]),
            ).fetchone()
            if duplicates and payload.get("allow_duplicate") is not True:
                raise InventoryError(
                    "Ein gleicher oder sehr ähnlicher Kassenbon wurde bereits importiert. Prüfe den Hinweis und bestätige bei Bedarf den separaten Import.",
                    status_code=409, code="receipt_duplicate",
                    details={"matching_receipt_id": duplicates["id"]},
                )

            bookings_by_key: dict[tuple, dict[str, Any]] = {}
            for row in rows:
                if row["decision"] == "skip":
                    continue
                if row["decision"] == "new":
                    item = self.inventory.create_in_transaction(connection, {
                        "name": row["name"], "barcode": row["barcode"] or None,
                        "category": row["category"] or "Sonstiges", "location": row["location"],
                        "unit": row["unit"] or "Stück", "tracking_mode": "simple",
                        "stock_status": "unknown",
                    })
                    action = "initialize"
                    mode = row["tracking_mode"]
                else:
                    found = connection.execute(
                        "SELECT * FROM inventory_items WHERE id = ?", (row["item_id"],)
                    ).fetchone()
                    if found is None:
                        raise InventoryError("Ein ausgewählter Lagerartikel existiert nicht mehr.", status_code=409, field="item_id")
                    item = dict(found)
                    if item["quantity"] is None or item["tracking_mode"] == "simple" or item["stock_status"] != "known":
                        action = "initialize"
                        mode = row.get("tracking_mode")
                        if not isinstance(mode, str) or mode not in {"inventory", "exact"}:
                            raise InventoryError(
                                f"Für „{item['name']}“ ist noch kein Zahlenbestand erfasst. Wähle ausdrücklich einen Bestandsmodus.",
                                status_code=409, field="tracking_mode", code="receipt_initial_stock_confirmation_required",
                            )
                    else:
                        action = "receive"
                        mode = item["tracking_mode"]
                group_key = (item["id"], action)
                booking = bookings_by_key.setdefault(group_key, {
                    "item_id": item["id"], "action": action, "tracking_mode": mode,
                    "quantity": 0, "line_ids": [],
                })
                if booking["tracking_mode"] != mode:
                    raise InventoryError(
                        f"Für mehrere Zeilen des Artikels „{item['name']}“ wurde ein unterschiedliches Bestandsmodell gewählt.",
                        field="tracking_mode",
                    )
                quantity = booking["quantity"] + row["quantity"]
                if quantity > self.MAX_QUANTITY:
                    raise InventoryError("Die aufsummierte Bonmenge überschreitet den unterstützten Höchstwert.", field="quantity")
                booking["quantity"] = quantity
                booking["line_ids"].extend(row["line_ids"])
                if row.get("learn_alias"):
                    alias_label = row["label"] or row.get("name", "")
                    self._save_alias(connection, receipt["merchant"], alias_label, item["id"], row.get("replace_alias", False))

            movements = self.movements.book_batch_in_transaction(
                connection, receipt_id, list(bookings_by_key.values())
            )
            connection.execute(
                """UPDATE receipt_imports SET status = 'imported', idempotency_key = ?,
                   request_hash = ?, duplicate_override = ?, imported_at = ? WHERE id = ?""",
                (key, request_hash, int(payload.get("allow_duplicate") is True and duplicates is not None), self._now(), receipt_id),
            )
            result = {"receipt_id": receipt_id, "movements": movements, "replayed": False}
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _receipt_summary(self, connection, receipt_id: str, replayed: bool = False) -> dict[str, Any]:
        receipt = self._load_receipt(connection, receipt_id)
        rows = connection.execute(
            """SELECT m.*, i.name AS item_name, u.id AS undone_by_movement_id
               FROM stock_movements AS m JOIN inventory_items AS i ON i.id = m.item_id
               LEFT JOIN stock_movements AS u ON u.undo_of_movement_id = m.id
               WHERE m.receipt_import_id = ? ORDER BY m.id""", (receipt_id,),
        ).fetchall()
        return {
            "receipt": {key: receipt[key] for key in (
                "id", "merchant", "fingerprint_strength", "line_count", "status",
                "duplicate_override", "created_at", "imported_at", "undone_at",
            )},
            "movements": [dict(row) for row in rows], "replayed": replayed,
        }

    def undo_receipt(self, receipt_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) - {"confirmed", "idempotency_key"}:
            raise InventoryError("Die Anfrage muss eine gültige Rückgängig-Bestätigung enthalten.")
        if payload.get("confirmed") is not True:
            raise InventoryError("Bitte bestätige, dass alle Buchungen dieses Bons rückgängig gemacht werden.", field="confirmed")
        key = self._required_key(payload)
        request_hash = self._request_hash(payload)
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            receipt = self._load_receipt(connection, receipt_id)
            if receipt["status"] == "undone":
                if receipt["undo_idempotency_key"] == key and receipt["undo_request_hash"] == request_hash:
                    result = self._receipt_summary(connection, receipt_id, replayed=True)
                    connection.commit()
                    return result
                raise InventoryError("Dieser Bon wurde bereits rückgängig gemacht.", status_code=409, code="receipt_already_undone")
            if receipt["status"] != "imported":
                raise InventoryError("Dieser Bon enthält noch keine importierten Buchungen.", status_code=409)
            key_owner = connection.execute(
                "SELECT id FROM receipt_imports WHERE undo_idempotency_key = ? AND id != ?",
                (key, receipt_id),
            ).fetchone()
            if key_owner:
                raise InventoryError("Der Undo-Idempotenzschlüssel wurde bereits für einen anderen Bon verwendet.", status_code=409)
            movements = self.movements.undo_batch_in_transaction(connection, receipt_id, key)
            connection.execute(
                """UPDATE receipt_imports SET status = 'undone', undo_idempotency_key = ?,
                   undo_request_hash = ?, undone_at = ? WHERE id = ?""",
                (key, request_hash, self._now(), receipt_id),
            )
            result = {"receipt_id": receipt_id, "movements": movements, "replayed": False}
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            return self._receipt_summary(connection, receipt_id)
        finally:
            connection.close()
