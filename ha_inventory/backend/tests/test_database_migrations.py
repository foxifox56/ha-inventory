from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.database import Database, SCHEMA_VERSION
from backend.inventory.repository import InventoryRepository
from backend.inventory.service import InventoryService


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fresh_schema_has_unknown_not_one_as_the_default(self) -> None:
        database = Database(self.data_dir)
        database.initialize()
        service = InventoryService(InventoryRepository(database))
        item = service.create({"name": "Scanartikel", "barcode": "0001"})
        self.assertIsNone(item["quantity"])
        self.assertEqual(item["stock_status"], "unknown")
        self.assertEqual(item["tracking_mode"], "simple")

        connection = database.connect()
        try:
            version = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
            self.assertEqual(version, SCHEMA_VERSION)
            quantity_default = connection.execute(
                "PRAGMA table_info(inventory_items)"
            ).fetchall()
            quantity_column = next(row for row in quantity_default if row["name"] == "quantity")
            self.assertIn(quantity_column["dflt_value"], (None, "NULL"))
            connection.execute(
                "INSERT INTO inventory_items(name, created_at, updated_at) "
                "VALUES ('SQL-Standard', '2026-11-23T00:00:00Z', '2026-11-23T00:00:00Z')"
            )
            defaults = connection.execute(
                "SELECT quantity, tracking_mode, stock_status FROM inventory_items "
                "WHERE name = 'SQL-Standard'"
            ).fetchone()
            self.assertIsNone(defaults["quantity"])
            self.assertEqual(defaults["tracking_mode"], "simple")
            self.assertEqual(defaults["stock_status"], "unknown")
        finally:
            connection.close()

    def test_v1_migration_marks_ambiguous_old_quantity_as_unknown(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.data_dir / "inventory.sqlite3")
        try:
            connection.executescript(
                """CREATE TABLE schema_migrations (
                       version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                   CREATE TABLE inventory_items (
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
                       updated_at TEXT NOT NULL);
                   CREATE INDEX inventory_items_name_idx
                       ON inventory_items(name COLLATE NOCASE);
                   CREATE INDEX inventory_items_category_idx
                       ON inventory_items(category COLLATE NOCASE);
                   INSERT INTO schema_migrations VALUES (1, '2026-11-23T00:00:00Z');
                   INSERT INTO inventory_items (
                       id, name, barcode, category, quantity, unit, location,
                       minimum_quantity, notes, created_at, updated_at
                   ) VALUES (
                       7, 'Schrauben', '0007', 'Werkzeuge', 12, 'Stück', 'Keller',
                       3, 'Altbestand', '2026-11-23T00:00:00Z', '2026-11-23T00:00:00Z'
                   );"""
            )
        finally:
            connection.close()

        database = Database(self.data_dir)
        database.initialize()
        service = InventoryService(InventoryRepository(database))
        migrated = service.get(7)
        self.assertIsNone(migrated["quantity"])
        self.assertEqual(migrated["tracking_mode"], "simple")
        self.assertEqual(migrated["stock_status"], "unknown")
        self.assertEqual(migrated["barcode"], "0007")
        self.assertEqual(migrated["notes"], "Altbestand")
