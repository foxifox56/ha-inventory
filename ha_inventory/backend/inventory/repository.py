"""Persistence operations for inventory records."""

from __future__ import annotations

import sqlite3
from typing import Any

from ..database import Database


class InventoryRepository:
    FIELDS = {
        "name",
        "barcode",
        "category",
        "quantity",
        "unit",
        "location",
        "minimum_quantity",
        "notes",
        "created_at",
        "updated_at",
    }

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _as_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def list_items(self, search: str = "", category: str = "") -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            pattern = f"%{search}%"
            clauses.append("(name LIKE ? OR barcode LIKE ? OR location LIKE ?)")
            params.extend((pattern, pattern, pattern))
        if category:
            clauses.append("category = ? COLLATE NOCASE")
            params.append(category)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        connection = self.database.connect()
        try:
            rows = connection.execute(
                f"SELECT * FROM inventory_items{where} ORDER BY name COLLATE NOCASE, id",
                params,
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def get(self, item_id: int) -> dict[str, Any] | None:
        connection = self.database.connect()
        try:
            row = connection.execute(
                "SELECT * FROM inventory_items WHERE id = ?", (item_id,)
            ).fetchone()
            return self._as_dict(row)
        finally:
            connection.close()

    def get_by_barcode(self, barcode: str) -> dict[str, Any] | None:
        connection = self.database.connect()
        try:
            row = connection.execute(
                "SELECT * FROM inventory_items WHERE barcode = ?", (barcode,)
            ).fetchone()
            return self._as_dict(row)
        finally:
            connection.close()

    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        columns = list(values)
        connection = self.database.connect()
        try:
            with connection:
                cursor = connection.execute(
                    f"INSERT INTO inventory_items ({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' for _ in columns)})",
                    [values[column] for column in columns],
                )
                row = connection.execute(
                    "SELECT * FROM inventory_items WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
                return dict(row)
        finally:
            connection.close()

    def update(self, item_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
        if not values:
            return self.get(item_id)
        columns = list(values)
        connection = self.database.connect()
        try:
            with connection:
                cursor = connection.execute(
                    "UPDATE inventory_items SET "
                    + ", ".join(f"{column} = ?" for column in columns)
                    + " WHERE id = ?",
                    [values[column] for column in columns] + [item_id],
                )
                if cursor.rowcount == 0:
                    return None
                row = connection.execute(
                    "SELECT * FROM inventory_items WHERE id = ?", (item_id,)
                ).fetchone()
                return dict(row)
        finally:
            connection.close()

    def delete(self, item_id: int) -> bool:
        connection = self.database.connect()
        try:
            with connection:
                cursor = connection.execute(
                    "DELETE FROM inventory_items WHERE id = ?", (item_id,)
                )
                return cursor.rowcount > 0
        finally:
            connection.close()
