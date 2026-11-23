from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.database import Database, SCHEMA_VERSION
from backend.inventory.repository import InventoryRepository
from backend.inventory.service import InventoryService
from backend.inventory.movements import StockMovementService


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

    def test_v4_upgrade_adds_history_without_changing_existing_item_data(self) -> None:
        database = Database(self.data_dir)
        database.initialize()
        service = InventoryService(InventoryRepository(database))
        item = service.create({
            "name": "Milch", "barcode": "000123", "category": "Lebensmittel",
            "tracking_mode": "exact", "quantity": 2, "location": "Küche",
            "brand": "Beispiel", "product_size": "1 l", "notes": "Altbestand",
        })
        connection = database.connect()
        try:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("DROP TABLE stock_movements")
            connection.execute("DROP TABLE receipt_product_aliases")
            connection.execute("DROP TABLE receipt_imports")
            connection.execute("DELETE FROM schema_migrations WHERE version >= 5")
            connection.commit()
        finally:
            connection.close()

        database.initialize()
        migrated = InventoryService(InventoryRepository(database)).get(item["id"])
        self.assertEqual(migrated["id"], item["id"])
        self.assertEqual(migrated["barcode"], "000123")
        self.assertEqual(migrated["quantity"], 2)
        self.assertEqual(migrated["tracking_mode"], "exact")
        self.assertEqual(migrated["location"], "Küche")
        self.assertEqual(migrated["brand"], "Beispiel")
        self.assertEqual(migrated["notes"], "Altbestand")
        connection = database.connect()
        try:
            self.assertIsNotNone(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_movements'"
            ).fetchone())
            self.assertEqual(connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0], SCHEMA_VERSION)
        finally:
            connection.close()

    def test_v5_upgrade_preserves_movement_ids_and_undo_relationships_through_v7(self) -> None:
        database = Database(self.data_dir)
        database.initialize()
        item = InventoryService(InventoryRepository(database)).create({
            "name": "Schrauben", "tracking_mode": "exact", "quantity": 5,
        })
        service = StockMovementService(database)
        received = service.book(item["id"], {
            "action": "receive", "quantity": 2, "idempotency_key": "migration-receive",
        })
        undone = service.undo(received["id"], {"idempotency_key": "migration-undo"})

        connection = database.connect()
        try:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("DROP TABLE receipt_product_aliases")
            connection.execute("DROP TABLE receipt_imports")
            connection.execute(
                """CREATE TABLE stock_movements_v5 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
                    action TEXT NOT NULL CHECK(action IN ('receive', 'consume', 'initialize', 'undo')),
                    source TEXT NOT NULL DEFAULT 'manual',
                    delta_quantity INTEGER NOT NULL CHECK(delta_quantity != 0),
                    quantity_before REAL CHECK(quantity_before IS NULL OR quantity_before >= 0),
                    quantity_after REAL CHECK(quantity_after IS NULL OR quantity_after >= 0),
                    tracking_mode_before TEXT NOT NULL CHECK(tracking_mode_before IN ('simple', 'inventory', 'exact')),
                    tracking_mode_after TEXT NOT NULL CHECK(tracking_mode_after IN ('simple', 'inventory', 'exact')),
                    stock_status_before TEXT NOT NULL CHECK(stock_status_before IN ('unknown', 'present', 'out_of_stock', 'known')),
                    stock_status_after TEXT NOT NULL CHECK(stock_status_after IN ('unknown', 'present', 'out_of_stock', 'known')),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    undo_of_movement_id INTEGER UNIQUE REFERENCES stock_movements_v5(id),
                    created_at TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                )"""
            )
            connection.execute(
                """INSERT INTO stock_movements_v5 (
                    id, item_id, action, source, delta_quantity, quantity_before, quantity_after,
                    tracking_mode_before, tracking_mode_after, stock_status_before,
                    stock_status_after, idempotency_key, undo_of_movement_id, created_at, note
                ) SELECT id, item_id, action, source, delta_quantity, quantity_before, quantity_after,
                    tracking_mode_before, tracking_mode_after, stock_status_before, stock_status_after,
                    idempotency_key, undo_of_movement_id, created_at, note
                FROM stock_movements"""
            )
            connection.execute("DROP TABLE stock_movements")
            connection.execute("ALTER TABLE stock_movements_v5 RENAME TO stock_movements")
            connection.execute(
                "CREATE INDEX stock_movements_item_created_idx ON stock_movements(item_id, id DESC)"
            )
            connection.execute("DELETE FROM schema_migrations WHERE version >= 6")
            connection.commit()
        finally:
            connection.close()

        database.initialize()
        migrated_rows = StockMovementService(database).list_for_item(item["id"])
        by_id = {row["id"]: row for row in migrated_rows}
        self.assertEqual(set(by_id), {received["id"], undone["id"]})
        self.assertEqual(by_id[received["id"]]["idempotency_key"], "migration-receive")
        self.assertEqual(by_id[undone["id"]]["undo_of_movement_id"], received["id"])
        self.assertEqual(InventoryService(InventoryRepository(database)).get(item["id"])["quantity"], 5)
        connection = database.connect()
        try:
            self.assertEqual(connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0], SCHEMA_VERSION)
            # The rebuilt ledger accepts a zero initialization and its inverse.
            schema = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='stock_movements'"
            ).fetchone()[0]
            self.assertIn("action = 'initialize'", schema)
        finally:
            connection.close()

    def test_v6_to_v7_is_additive_and_preserves_items_and_movement_history(self) -> None:
        database = Database(self.data_dir)
        database.initialize()
        inventory = InventoryService(InventoryRepository(database))
        item = inventory.create({"name": "Kabelbinder", "barcode": "00042", "tracking_mode": "exact", "quantity": 8})
        movements = StockMovementService(database)
        received = movements.book(item["id"], {"action": "receive", "quantity": 2, "idempotency_key": "v6-receive"})
        undone = movements.undo(received["id"], {"idempotency_key": "v6-undo"})

        connection = database.connect()
        try:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("DROP TABLE receipt_product_aliases")
            connection.execute("DROP TABLE receipt_imports")
            connection.execute(
                """CREATE TABLE stock_movements_v6_fixture (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
                    action TEXT NOT NULL CHECK(action IN ('receive', 'consume', 'initialize', 'undo')),
                    source TEXT NOT NULL DEFAULT 'manual',
                    delta_quantity INTEGER NOT NULL CHECK(delta_quantity != 0 OR action = 'initialize'
                      OR (action = 'undo' AND undo_of_movement_id IS NOT NULL)),
                    quantity_before REAL CHECK(quantity_before IS NULL OR quantity_before >= 0),
                    quantity_after REAL CHECK(quantity_after IS NULL OR quantity_after >= 0),
                    tracking_mode_before TEXT NOT NULL,
                    tracking_mode_after TEXT NOT NULL,
                    stock_status_before TEXT NOT NULL,
                    stock_status_after TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    undo_of_movement_id INTEGER UNIQUE REFERENCES stock_movements_v6_fixture(id),
                    created_at TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                )"""
            )
            connection.execute(
                """INSERT INTO stock_movements_v6_fixture (
                    id, item_id, action, source, delta_quantity, quantity_before, quantity_after,
                    tracking_mode_before, tracking_mode_after, stock_status_before,
                    stock_status_after, idempotency_key, undo_of_movement_id, created_at, note
                ) SELECT id, item_id, action, source, delta_quantity, quantity_before, quantity_after,
                    tracking_mode_before, tracking_mode_after, stock_status_before,
                    stock_status_after, idempotency_key, undo_of_movement_id, created_at, note
                  FROM stock_movements"""
            )
            connection.execute("DROP TABLE stock_movements")
            connection.execute("ALTER TABLE stock_movements_v6_fixture RENAME TO stock_movements")
            connection.execute("DELETE FROM schema_migrations WHERE version = 7")
            connection.commit()
        finally:
            connection.close()

        database.initialize()
        migrated = InventoryService(InventoryRepository(database)).get(item["id"])
        rows = StockMovementService(database).list_for_item(item["id"])
        by_id = {row["id"]: row for row in rows}
        self.assertEqual((migrated["barcode"], migrated["quantity"], migrated["tracking_mode"]), ("00042", 8, "exact"))
        self.assertEqual(set(by_id), {received["id"], undone["id"]})
        self.assertEqual(by_id[received["id"]]["idempotency_key"], "v6-receive")
        self.assertEqual(by_id[undone["id"]]["undo_of_movement_id"], received["id"])
        self.assertIsNone(by_id[received["id"]]["receipt_import_id"])
        connection = database.connect()
        try:
            self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 7)
            self.assertIsNotNone(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='receipt_imports'").fetchone())
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

    def test_v3_enrichment_migration_preserves_existing_items_and_stock(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.data_dir / "inventory.sqlite3")
        try:
            connection.executescript(
                """CREATE TABLE schema_migrations (
                       version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                   CREATE TABLE inventory_items (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       name TEXT NOT NULL, barcode TEXT UNIQUE,
                       category TEXT NOT NULL DEFAULT 'Sonstiges',
                       quantity REAL DEFAULT NULL CHECK(quantity IS NULL OR quantity >= 0),
                       unit TEXT NOT NULL DEFAULT 'Stück', location TEXT NOT NULL DEFAULT '',
                       minimum_quantity REAL NOT NULL DEFAULT 0 CHECK(minimum_quantity >= 0),
                       notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                       updated_at TEXT NOT NULL,
                       tracking_mode TEXT NOT NULL DEFAULT 'simple'
                           CHECK(tracking_mode IN ('simple', 'inventory', 'exact')),
                       stock_status TEXT NOT NULL DEFAULT 'unknown'
                           CHECK(stock_status IN ('unknown', 'present', 'out_of_stock', 'known')));
                   INSERT INTO schema_migrations VALUES (3, '2026-11-23T00:00:00Z');
                   INSERT INTO inventory_items (
                       id, name, barcode, category, quantity, unit, location,
                       minimum_quantity, notes, created_at, updated_at, tracking_mode,
                       stock_status
                   ) VALUES (
                       27, 'Dübel', '00027', 'Werkzeuge', 12, 'Stück', 'Werkstatt',
                       3, 'Bestätigter Bestand', '2026-11-20T00:00:00Z',
                       '2026-11-21T00:00:00Z', 'exact', 'known'
                   );
                   INSERT INTO inventory_items (
                       id, name, barcode, category, quantity, unit, location,
                       minimum_quantity, notes, created_at, updated_at, tracking_mode,
                       stock_status
                   ) VALUES (
                       28, 'Akkuschrauber', 'TOOL-001', 'Werkzeuge', 4.5, 'Stück', 'Garage',
                       1, 'Alphanumerischer Bestand', '2026-11-20T00:00:00Z',
                       '2026-11-22T00:00:00Z', 'inventory', 'known'
                   );"""
            )
        finally:
            connection.close()

        database = Database(self.data_dir)
        database.initialize()
        migrated = InventoryService(InventoryRepository(database)).get(27)
        self.assertEqual(migrated["id"], 27)
        self.assertEqual(migrated["barcode"], "00027")
        self.assertEqual(migrated["quantity"], 12)
        self.assertEqual(migrated["stock_status"], "known")
        self.assertEqual(migrated["tracking_mode"], "exact")
        self.assertEqual(migrated["notes"], "Bestätigter Bestand")
        self.assertEqual(migrated["brand"], "")
        self.assertEqual(migrated["product_size"], "")
        self.assertEqual(migrated["image_url"], "")
        self.assertEqual(migrated["image_license"], "")

        migrated_alpha = InventoryService(InventoryRepository(database)).get(28)
        self.assertEqual(migrated_alpha["id"], 28)
        self.assertEqual(migrated_alpha["barcode"], "TOOL-001")
        self.assertEqual(migrated_alpha["quantity"], 4.5)
        self.assertEqual(migrated_alpha["stock_status"], "known")
        self.assertEqual(migrated_alpha["tracking_mode"], "inventory")
        self.assertEqual(migrated_alpha["location"], "Garage")
        self.assertEqual(migrated_alpha["notes"], "Alphanumerischer Bestand")
