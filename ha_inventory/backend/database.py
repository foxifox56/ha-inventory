"""SQLite connection management and schema migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 1


class Database:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.path = data_dir / "inventory.sqlite3"

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()["version"]
            if current < 1:
                with connection:
                    connection.execute(
                        """CREATE TABLE inventory_items (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT NOT NULL,
                            barcode TEXT UNIQUE,
                            category TEXT NOT NULL DEFAULT 'Sonstiges',
                            quantity REAL NOT NULL DEFAULT 1 CHECK(quantity >= 0),
                            unit TEXT NOT NULL DEFAULT 'Stück',
                            location TEXT NOT NULL DEFAULT '',
                            minimum_quantity REAL NOT NULL DEFAULT 0 CHECK(minimum_quantity >= 0),
                            notes TEXT NOT NULL DEFAULT '',
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )"""
                    )
                    connection.execute(
                        "CREATE INDEX inventory_items_name_idx "
                        "ON inventory_items(name COLLATE NOCASE)"
                    )
                    connection.execute(
                        "CREATE INDEX inventory_items_category_idx "
                        "ON inventory_items(category COLLATE NOCASE)"
                    )
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) "
                        "VALUES (1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
                    )
                current = 1
            if current != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported database schema version {current}; "
                    f"this app supports {SCHEMA_VERSION}."
                )
        finally:
            connection.close()
