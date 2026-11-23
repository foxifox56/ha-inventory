"""Transactional stock bookings and their durable audit history."""

from __future__ import annotations

import sqlite3
import math
import json
from datetime import datetime, timezone
from typing import Any

from ..database import Database
from ..errors import InventoryError


class StockMovementService:
    """Change a persisted item's stock only with an audited movement."""

    ACTIONS = {"receive", "consume", "initialize"}
    # Keep counts exact in SQLite and JavaScript clients. This is lower than
    # SQLite's signed 64-bit integer limit and avoids JS number rounding.
    MAX_SAFE_QUANTITY = (1 << 53) - 1

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _positive_integer(value: Any) -> int:
        if (isinstance(value, bool) or not isinstance(value, int) or value <= 0
                or value > StockMovementService.MAX_SAFE_QUANTITY):
            raise InventoryError(
                "Die Buchungsmenge muss eine ganze Zahl zwischen 1 und 9.007.199.254.740.991 sein.",
                field="quantity",
            )
        return value

    @staticmethod
    def _initial_quantity(value: Any) -> int:
        if (isinstance(value, bool) or not isinstance(value, int) or value < 0
                or value > StockMovementService.MAX_SAFE_QUANTITY):
            raise InventoryError(
                "Der Startbestand muss eine ganze Zahl zwischen 0 und 9.007.199.254.740.991 sein.",
                field="quantity",
            )
        return value

    @staticmethod
    def _validate_resulting_quantity(value: Any) -> None:
        """Reject a resulting count before binding it to SQLite."""
        valid = isinstance(value, int) and not isinstance(value, bool)
        if isinstance(value, float):
            valid = math.isfinite(value)
        if not valid or value > StockMovementService.MAX_SAFE_QUANTITY:
            raise InventoryError(
                "Der resultierende Bestand überschreitet den unterstützten Höchstwert.",
                field="quantity",
            )

    @staticmethod
    def _key(payload: dict[str, Any]) -> str:
        value = payload.get("idempotency_key")
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
            raise InventoryError("Es fehlt ein gültiger Idempotenzschlüssel.", field="idempotency_key")
        return value.strip()

    @staticmethod
    def _label(payload: dict[str, Any], field: str, default: str, limit: int) -> str:
        value = payload.get(field, default)
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise InventoryError(f"Ungültiger Wert für {field}.", field=field)
        return value.strip() or default

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    @staticmethod
    def _movement(connection: sqlite3.Connection, movement_id: int) -> dict[str, Any] | None:
        row = connection.execute("SELECT * FROM stock_movements WHERE id = ?", (movement_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _existing_key(connection: sqlite3.Connection, key: str) -> dict[str, Any] | None:
        row = connection.execute("SELECT * FROM stock_movements WHERE idempotency_key = ?", (key,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _same_request(
        existing: dict[str, Any], *, item_id: int, action: str, quantity: int,
        source: str, note: str, undo_of: int | None = None,
        tracking_mode: str | None = None, confirm_initial_stock: Any = None,
        receipt_import_id: str | None = None,
    ) -> bool:
        return (
            existing["item_id"] == item_id and existing["action"] == action
            and abs(existing["delta_quantity"]) == quantity
            and existing["source"] == source and existing["note"] == note
            and existing["undo_of_movement_id"] == undo_of
            and existing.get("receipt_import_id") == receipt_import_id
            and (action != "initialize" or (
                tracking_mode == existing["tracking_mode_after"]
                and confirm_initial_stock is True
            ))
        )

    def book(self, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            movement = self._book_in_transaction(connection, item_id, payload)
            connection.commit()
            return movement
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _book_in_transaction(
        self, connection: sqlite3.Connection, item_id: int, payload: dict[str, Any],
        *, receipt_import_id: str | None = None, receipt_line_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise InventoryError("Die Anfrage muss ein JSON-Objekt enthalten.")
        allowed = {"action", "quantity", "idempotency_key", "source", "note"}
        if payload.get("action") == "initialize":
            allowed |= {"confirm_initial_stock", "tracking_mode"}
        unknown = set(payload) - allowed
        if unknown:
            raise InventoryError(f"Unbekanntes Feld: {sorted(unknown)[0]}.")
        action = payload.get("action")
        if not isinstance(action, str) or action not in self.ACTIONS:
            raise InventoryError("Aktion muss receive, consume oder initialize sein.", field="action")
        quantity = (
            self._initial_quantity(payload.get("quantity"))
            if action == "initialize"
            else self._positive_integer(payload.get("quantity"))
        )
        key = self._key(payload)
        source = self._label(payload, "source", "manual", 32)
        note = self._label(payload, "note", "", 500)

        replay = self._existing_key(connection, key)
        if replay:
            if not self._same_request(
                replay, item_id=item_id, action=action, quantity=quantity,
                source=source, note=note, tracking_mode=payload.get("tracking_mode"),
                confirm_initial_stock=payload.get("confirm_initial_stock"),
                receipt_import_id=receipt_import_id,
            ):
                raise InventoryError("Der Idempotenzschlüssel wurde bereits für eine andere Buchung verwendet.", status_code=409)
            replay["replayed"] = True
            return replay

        item = connection.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        if item is None:
            raise InventoryError("Artikel nicht gefunden.", status_code=404)
        before = dict(item)
        now = self._timestamp()
        if action == "initialize":
            if payload.get("confirm_initial_stock") is not True:
                raise InventoryError("Bitte bestätige ausdrücklich, dass du den Startbestand festlegst.", field="confirm_initial_stock")
            if before["quantity"] is not None or before["stock_status"] == "known":
                raise InventoryError("Für diesen Artikel ist bereits ein Bestand erfasst.", status_code=409)
            mode = payload.get("tracking_mode")
            if not isinstance(mode, str) or mode not in {"inventory", "exact"}:
                raise InventoryError("Wähle Inventar oder exakten Bestand.", field="tracking_mode")
            status = "known"
            delta = quantity
            after_quantity: int | None = quantity
        else:
            if before["tracking_mode"] == "simple" or before["quantity"] is None or before["stock_status"] != "known":
                raise InventoryError("Der numerische Bestand ist unbekannt. Lege zuerst ausdrücklich einen Startbestand fest.", status_code=409)
            mode = before["tracking_mode"]
            status = "known"
            delta = quantity if action == "receive" else -quantity
            after_quantity = before["quantity"] + delta
            if after_quantity < 0:
                raise InventoryError("Die Buchung würde den Lagerbestand unter 0 senken.", status_code=409)
        self._validate_resulting_quantity(after_quantity)
        if abs(delta) > self.MAX_SAFE_QUANTITY:
            raise InventoryError("Die Buchungsmenge überschreitet den unterstützten Höchstwert.", field="quantity")

        connection.execute(
            "UPDATE inventory_items SET tracking_mode = ?, stock_status = ?, quantity = ?, updated_at = ? WHERE id = ?",
            (mode, status, after_quantity, now, item_id),
        )
        cursor = connection.execute(
            """INSERT INTO stock_movements (
                item_id, action, source, delta_quantity, quantity_before, quantity_after,
                tracking_mode_before, tracking_mode_after, stock_status_before,
                stock_status_after, idempotency_key, created_at, note,
                receipt_import_id, receipt_line_ids
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, action, source, delta, before["quantity"], after_quantity,
             before["tracking_mode"], mode, before["stock_status"], status,
             key, now, note, receipt_import_id, json.dumps(receipt_line_ids or [])),
        )
        movement = self._movement(connection, cursor.lastrowid)
        assert movement is not None
        movement["replayed"] = False
        return movement

    def book_batch_in_transaction(
        self, connection: sqlite3.Connection, receipt_import_id: str, bookings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Book a receipt's grouped receive/initialize operations atomically."""
        movements = []
        for index, booking in enumerate(bookings, start=1):
            line_ids = [int(value) for value in booking["line_ids"]]
            note = f"Kassenbon {receipt_import_id} · Zeilen {','.join(map(str, line_ids))}"
            payload = {
                "action": booking["action"], "quantity": booking["quantity"],
                "source": "receipt", "note": note[:500],
                "idempotency_key": f"receipt:{receipt_import_id}:book:{index}",
            }
            if booking["action"] == "initialize":
                payload["tracking_mode"] = booking["tracking_mode"]
                payload["confirm_initial_stock"] = True
            movements.append(self._book_in_transaction(
                connection, int(booking["item_id"]), payload,
                receipt_import_id=receipt_import_id, receipt_line_ids=line_ids,
            ))
        return movements

    def undo(self, movement_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            movement = self._undo_in_transaction(connection, movement_id, payload)
            connection.commit()
            return movement
        except sqlite3.IntegrityError as error:
            connection.rollback()
            if "undo_of_movement_id" in str(error) or "UNIQUE constraint" in str(error):
                raise InventoryError("Diese Buchung wurde bereits rückgängig gemacht oder der Schlüssel wird schon verwendet.", status_code=409) from error
            raise
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def undo_batch_in_transaction(
        self, connection: sqlite3.Connection, receipt_import_id: str,
        idempotency_key: str,
    ) -> list[dict[str, Any]]:
        """Undo every active movement from a receipt or fail the whole batch."""
        originals = connection.execute(
            """SELECT id FROM stock_movements
               WHERE receipt_import_id = ? AND action != 'undo'
               ORDER BY id DESC""",
            (receipt_import_id,),
        ).fetchall()
        if not originals:
            raise InventoryError("Für diesen Kassenbon gibt es keine Buchungen.", status_code=409)
        undos = []
        for index, row in enumerate(originals, start=1):
            undos.append(self._undo_in_transaction(connection, row["id"], {
                "idempotency_key": f"{idempotency_key}:{index}",
                "source": "receipt",
                "note": f"Kassenbon {receipt_import_id} rückgängig gemacht",
            }))
        return undos

    def _undo_in_transaction(
        self, connection: sqlite3.Connection, movement_id: int, payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise InventoryError("Die Anfrage muss ein JSON-Objekt enthalten.")
        unknown = set(payload) - {"idempotency_key", "source", "note"}
        if unknown:
            raise InventoryError(f"Unbekanntes Feld: {sorted(unknown)[0]}.")
        key = self._key(payload)
        source = self._label(payload, "source", "manual", 32)
        note = self._label(payload, "note", "Rückgängig gemacht", 500)
        original = self._movement(connection, movement_id)
        if original is None:
            raise InventoryError("Buchung nicht gefunden.", status_code=404)
        if original["action"] == "undo":
            raise InventoryError("Eine Rückgängig-Buchung kann nicht erneut rückgängig gemacht werden.", status_code=409)
        replay = self._existing_key(connection, key)
        if replay:
            if not self._same_request(
                replay, item_id=original["item_id"], action="undo",
                quantity=abs(original["delta_quantity"]), source=source,
                note=note, undo_of=movement_id,
            ):
                raise InventoryError("Der Idempotenzschlüssel wurde bereits für eine andere Buchung verwendet.", status_code=409)
            replay["replayed"] = True
            return replay
        if connection.execute(
            "SELECT 1 FROM stock_movements WHERE undo_of_movement_id = ?", (movement_id,)
        ).fetchone():
            raise InventoryError("Diese Buchung wurde bereits rückgängig gemacht.", status_code=409)

        item_row = connection.execute(
            "SELECT * FROM inventory_items WHERE id = ?", (original["item_id"],)
        ).fetchone()
        if item_row is None:
            raise InventoryError("Artikel nicht gefunden.", status_code=404)
        item = dict(item_row)
        if original["action"] == "initialize":
            later_active = connection.execute(
                """SELECT 1 FROM stock_movements AS later
                   WHERE later.item_id = ? AND later.id > ? AND later.action != 'undo'
                     AND NOT EXISTS (
                         SELECT 1 FROM stock_movements AS reversal
                         WHERE reversal.undo_of_movement_id = later.id
                     )
                   LIMIT 1""",
                (original["item_id"], movement_id),
            ).fetchone()
            current_matches_baseline = (
                item["quantity"] == original["quantity_after"]
                and item["tracking_mode"] == original["tracking_mode_after"]
                and item["stock_status"] == original["stock_status_after"]
            )
            if later_active or not current_matches_baseline:
                raise InventoryError("Der Startbestand kann erst rückgängig gemacht werden, wenn spätere Buchungen zuerst aufgehoben sind.", status_code=409)
            after_quantity = None
            after_mode = original["tracking_mode_before"]
            after_status = original["stock_status_before"]
            delta = -abs(original["delta_quantity"])
        else:
            if item["quantity"] is None or item["tracking_mode"] == "simple":
                raise InventoryError("Der aktuelle Bestand ist unbekannt und kann nicht sicher rückgängig gebucht werden.", status_code=409)
            delta = -original["delta_quantity"]
            after_quantity = item["quantity"] + delta
            if after_quantity < 0:
                raise InventoryError("Rückgängig würde den Bestand unter 0 senken. Hebe zuerst spätere Verbrauchsbuchungen auf.", status_code=409)
            self._validate_resulting_quantity(after_quantity)
            after_mode = item["tracking_mode"]
            after_status = "known"
        if abs(delta) > self.MAX_SAFE_QUANTITY:
            raise InventoryError("Die Buchungsmenge überschreitet den unterstützten Höchstwert.", field="quantity")

        now = self._timestamp()
        connection.execute(
            "UPDATE inventory_items SET tracking_mode = ?, stock_status = ?, quantity = ?, updated_at = ? WHERE id = ?",
            (after_mode, after_status, after_quantity, now, item["id"]),
        )
        cursor = connection.execute(
            """INSERT INTO stock_movements (
                item_id, action, source, delta_quantity, quantity_before, quantity_after,
                tracking_mode_before, tracking_mode_after, stock_status_before,
                stock_status_after, idempotency_key, undo_of_movement_id, created_at, note,
                receipt_import_id, receipt_line_ids
            ) VALUES (?, 'undo', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item["id"], source, delta, item["quantity"], after_quantity,
             item["tracking_mode"], after_mode, item["stock_status"], after_status,
             key, movement_id, now, note, original.get("receipt_import_id"),
             original.get("receipt_line_ids", "[]")),
        )
        movement = self._movement(connection, cursor.lastrowid)
        assert movement is not None
        movement["replayed"] = False
        return movement

    def list_for_item(self, item_id: int) -> list[dict[str, Any]]:
        connection = self.database.connect()
        try:
            if connection.execute("SELECT 1 FROM inventory_items WHERE id = ?", (item_id,)).fetchone() is None:
                raise InventoryError("Artikel nicht gefunden.", status_code=404)
            rows = connection.execute(
                """SELECT m.*, u.id AS undone_by_movement_id
                   FROM stock_movements AS m
                   LEFT JOIN stock_movements AS u ON u.undo_of_movement_id = m.id
                   WHERE m.item_id = ? ORDER BY m.id DESC""", (item_id,)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()
