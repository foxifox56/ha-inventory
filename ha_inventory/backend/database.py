"""SQLite connection management and schema migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 7


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

            if current < 2:
                with connection:
                    connection.execute(
                        """CREATE TABLE inventory_items_v2 (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT NOT NULL,
                            barcode TEXT UNIQUE,
                            category TEXT NOT NULL DEFAULT 'Sonstiges',
                            quantity REAL DEFAULT NULL
                                CHECK(quantity IS NULL OR quantity >= 0),
                            unit TEXT NOT NULL DEFAULT 'Stück',
                            location TEXT NOT NULL DEFAULT '',
                            minimum_quantity REAL NOT NULL DEFAULT 0
                                CHECK(minimum_quantity >= 0),
                            notes TEXT NOT NULL DEFAULT '',
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )"""
                    )
                    connection.execute(
                        """INSERT INTO inventory_items_v2 (
                            id, name, barcode, category, quantity, unit, location,
                            minimum_quantity, notes, created_at, updated_at
                        ) SELECT id, name, barcode, category, quantity, unit, location,
                            minimum_quantity, notes, created_at, updated_at
                        FROM inventory_items"""
                    )
                    connection.execute("DROP TABLE inventory_items")
                    connection.execute(
                        "ALTER TABLE inventory_items_v2 RENAME TO inventory_items"
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
                        "VALUES (2, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
                    )
                current = 2

            if current < 3:
                with connection:
                    connection.execute(
                        """ALTER TABLE inventory_items ADD COLUMN tracking_mode TEXT
                            NOT NULL DEFAULT 'simple'
                            CHECK(tracking_mode IN ('simple', 'inventory', 'exact'))"""
                    )
                    connection.execute(
                        """ALTER TABLE inventory_items ADD COLUMN stock_status TEXT
                            NOT NULL DEFAULT 'unknown'
                            CHECK(stock_status IN ('unknown', 'present', 'out_of_stock', 'known'))"""
                    )
                    # Version 1 used a default count of 1, so stored numbers cannot
                    # be distinguished from phantom defaults. Keep item metadata but
                    # require every legacy count to be confirmed explicitly.
                    connection.execute(
                        """UPDATE inventory_items
                           SET tracking_mode = 'simple', stock_status = 'unknown',
                               quantity = NULL"""
                    )
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) "
                        "VALUES (3, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
                    )
                current = 3

            if current < 4:
                with connection:
                    # Product enrichment is metadata only. Add nullable-looking
                    # text fields with empty defaults so every v0.1/v0.2 row,
                    # barcode, stock value, and durable ID remains untouched.
                    connection.execute(
                        "ALTER TABLE inventory_items ADD COLUMN brand TEXT NOT NULL DEFAULT ''"
                    )
                    connection.execute(
                        "ALTER TABLE inventory_items ADD COLUMN product_size TEXT NOT NULL DEFAULT ''"
                    )
                    connection.execute(
                        "ALTER TABLE inventory_items ADD COLUMN image_url TEXT NOT NULL DEFAULT ''"
                    )
                    connection.execute(
                        "ALTER TABLE inventory_items ADD COLUMN image_license TEXT NOT NULL DEFAULT ''"
                    )
                    connection.execute(
                        "ALTER TABLE inventory_items ADD COLUMN data_source TEXT NOT NULL DEFAULT ''"
                    )
                    connection.execute(
                        "ALTER TABLE inventory_items ADD COLUMN source_url TEXT NOT NULL DEFAULT ''"
                    )
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) "
                        "VALUES (4, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
                    )
                current = 4

            if current < 5:
                with connection:
                    connection.execute(
                        """CREATE TABLE stock_movements (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            item_id INTEGER NOT NULL REFERENCES inventory_items(id)
                                ON DELETE RESTRICT,
                            action TEXT NOT NULL CHECK(action IN ('receive', 'consume', 'initialize', 'undo')),
                            source TEXT NOT NULL DEFAULT 'manual',
                            delta_quantity INTEGER NOT NULL CHECK(delta_quantity != 0),
                            quantity_before REAL CHECK(quantity_before IS NULL OR quantity_before >= 0),
                            quantity_after REAL CHECK(quantity_after IS NULL OR quantity_after >= 0),
                            tracking_mode_before TEXT NOT NULL
                                CHECK(tracking_mode_before IN ('simple', 'inventory', 'exact')),
                            tracking_mode_after TEXT NOT NULL
                                CHECK(tracking_mode_after IN ('simple', 'inventory', 'exact')),
                            stock_status_before TEXT NOT NULL
                                CHECK(stock_status_before IN ('unknown', 'present', 'out_of_stock', 'known')),
                            stock_status_after TEXT NOT NULL
                                CHECK(stock_status_after IN ('unknown', 'present', 'out_of_stock', 'known')),
                            idempotency_key TEXT NOT NULL UNIQUE,
                            undo_of_movement_id INTEGER UNIQUE REFERENCES stock_movements(id),
                            created_at TEXT NOT NULL,
                            note TEXT NOT NULL DEFAULT ''
                        )"""
                    )
                    connection.execute(
                        "CREATE INDEX stock_movements_item_created_idx "
                        "ON stock_movements(item_id, id DESC)"
                    )
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) "
                        "VALUES (5, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
                    )
                current = 5

            if current < 6:
                # A confirmed zero baseline is meaningful (known/0), so the
                # movement ledger must allow a zero delta for initialization
                # and its inverse. Rebuild only the journal table; item rows
                # and all existing movement IDs/keys remain untouched.
                connection.execute("PRAGMA foreign_keys = OFF")
                with connection:
                    connection.execute(
                        """CREATE TABLE stock_movements_v6 (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            item_id INTEGER NOT NULL REFERENCES inventory_items(id)
                                ON DELETE RESTRICT,
                            action TEXT NOT NULL CHECK(action IN ('receive', 'consume', 'initialize', 'undo')),
                            source TEXT NOT NULL DEFAULT 'manual',
                            delta_quantity INTEGER NOT NULL
                                CHECK(delta_quantity != 0 OR action = 'initialize'
                                  OR (action = 'undo' AND undo_of_movement_id IS NOT NULL)),
                            quantity_before REAL CHECK(quantity_before IS NULL OR quantity_before >= 0),
                            quantity_after REAL CHECK(quantity_after IS NULL OR quantity_after >= 0),
                            tracking_mode_before TEXT NOT NULL
                                CHECK(tracking_mode_before IN ('simple', 'inventory', 'exact')),
                            tracking_mode_after TEXT NOT NULL
                                CHECK(tracking_mode_after IN ('simple', 'inventory', 'exact')),
                            stock_status_before TEXT NOT NULL
                                CHECK(stock_status_before IN ('unknown', 'present', 'out_of_stock', 'known')),
                            stock_status_after TEXT NOT NULL
                                CHECK(stock_status_after IN ('unknown', 'present', 'out_of_stock', 'known')),
                            idempotency_key TEXT NOT NULL UNIQUE,
                            undo_of_movement_id INTEGER UNIQUE REFERENCES stock_movements_v6(id),
                            created_at TEXT NOT NULL,
                            note TEXT NOT NULL DEFAULT ''
                        )"""
                    )
                    connection.execute(
                        """INSERT INTO stock_movements_v6 (
                            id, item_id, action, source, delta_quantity, quantity_before,
                            quantity_after, tracking_mode_before, tracking_mode_after,
                            stock_status_before, stock_status_after, idempotency_key,
                            undo_of_movement_id, created_at, note
                        ) SELECT id, item_id, action, source, delta_quantity, quantity_before,
                            quantity_after, tracking_mode_before, tracking_mode_after,
                            stock_status_before, stock_status_after, idempotency_key,
                            undo_of_movement_id, created_at, note
                        FROM stock_movements"""
                    )
                    connection.execute("DROP TABLE stock_movements")
                    connection.execute("ALTER TABLE stock_movements_v6 RENAME TO stock_movements")
                    connection.execute(
                        "CREATE INDEX stock_movements_item_created_idx "
                        "ON stock_movements(item_id, id DESC)"
                    )
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) "
                        "VALUES (6, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
                    )
                connection.execute("PRAGMA foreign_keys = ON")
                violations = connection.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise RuntimeError("Foreign-key violations found during schema migration 6.")
                current = 6

            if current < 7:
                # Receipt imports keep only privacy-preserving fingerprints,
                # merchant/status metadata and learned user-confirmed aliases.
                # OCR images and complete OCR text are never persisted.
                with connection:
                    connection.execute(
                        """CREATE TABLE receipt_imports (
                            id TEXT PRIMARY KEY,
                            merchant TEXT NOT NULL CHECK(merchant IN ('rewe', 'kaufland', 'other')),
                            image_sha256 TEXT NOT NULL,
                            receipt_fingerprint TEXT NOT NULL,
                            fingerprint_strength TEXT NOT NULL CHECK(fingerprint_strength IN ('strong', 'weak')),
                            line_count INTEGER NOT NULL CHECK(line_count >= 0),
                            status TEXT NOT NULL CHECK(status IN ('recognized', 'imported', 'undone')),
                            idempotency_key TEXT UNIQUE,
                            request_hash TEXT,
                            undo_idempotency_key TEXT UNIQUE,
                            undo_request_hash TEXT,
                            duplicate_override INTEGER NOT NULL DEFAULT 0 CHECK(duplicate_override IN (0, 1)),
                            created_at TEXT NOT NULL,
                            imported_at TEXT,
                            undone_at TEXT
                        )"""
                    )
                    connection.execute(
                        """CREATE INDEX receipt_imports_fingerprint_idx
                           ON receipt_imports(merchant, receipt_fingerprint, status)"""
                    )
                    connection.execute(
                        """CREATE TABLE receipt_product_aliases (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            merchant TEXT NOT NULL CHECK(merchant IN ('rewe', 'kaufland', 'other')),
                            normalized_alias TEXT NOT NULL,
                            alias_text TEXT NOT NULL,
                            item_id INTEGER NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            UNIQUE(merchant, normalized_alias)
                        )"""
                    )
                    connection.execute(
                        """ALTER TABLE stock_movements ADD COLUMN receipt_import_id TEXT
                           REFERENCES receipt_imports(id) ON DELETE RESTRICT"""
                    )
                    connection.execute(
                        """ALTER TABLE stock_movements ADD COLUMN receipt_line_ids TEXT
                           NOT NULL DEFAULT '[]'"""
                    )
                    connection.execute(
                        """CREATE INDEX stock_movements_receipt_idx
                           ON stock_movements(receipt_import_id, id)"""
                    )
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) "
                        "VALUES (7, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
                    )
                current = 7

            if current != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported database schema version {current}; "
                    f"this app supports {SCHEMA_VERSION}."
                )
        finally:
            connection.close()
