from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.database import Database
from backend.errors import InventoryError
from backend.inventory.repository import InventoryRepository
from backend.inventory.service import InventoryService


class InventoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp_dir.name))
        database.initialize()
        self.service = InventoryService(InventoryRepository(database))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_and_find_barcode_preserves_leading_zeroes(self) -> None:
        item = self.service.create({"name": "Tomatendose", "barcode": "0040123456789"})
        self.assertEqual(item["barcode"], "0040123456789")
        self.assertEqual(self.service.get_by_barcode("0040123456789")["id"], item["id"])

    def test_create_defaults_to_unknown_simple_stock_without_phantom_quantity(self) -> None:
        item = self.service.create({"name": "Hammer"})
        self.assertEqual(item["category"], "Sonstiges")
        self.assertEqual(item["tracking_mode"], "simple")
        self.assertEqual(item["stock_status"], "unknown")
        self.assertIsNone(item["quantity"])
        self.assertEqual(item["minimum_quantity"], 0)

    def test_inventory_mode_can_have_unknown_or_estimated_quantity(self) -> None:
        unknown = self.service.create(
            {"name": "Kabelbinder", "tracking_mode": "inventory"}
        )
        estimated = self.service.create(
            {"name": "Schrauben", "tracking_mode": "inventory", "quantity": 2}
        )
        self.assertEqual((unknown["quantity"], unknown["stock_status"]), (None, "unknown"))
        self.assertEqual((estimated["quantity"], estimated["stock_status"]), (2, "known"))

    def test_exact_zero_is_known_and_distinct_from_unknown(self) -> None:
        zero = self.service.create(
            {"name": "Mehl", "tracking_mode": "exact", "quantity": 0}
        )
        unknown = self.service.create({"name": "Zucker", "tracking_mode": "exact"})
        self.assertEqual((zero["quantity"], zero["stock_status"]), (0, "known"))
        self.assertEqual((unknown["quantity"], unknown["stock_status"]), (None, "unknown"))

    def test_simple_status_does_not_invent_a_numeric_count(self) -> None:
        item = self.service.create({"name": "Reinigungsmittel", "stock_status": "present"})
        self.assertEqual(item["stock_status"], "present")
        self.assertIsNone(item["quantity"])
        with self.assertRaises(InventoryError):
            self.service.create({"name": "Farbe", "quantity": 1})

    def test_duplicate_barcode_returns_conflict(self) -> None:
        self.service.create({"name": "A", "barcode": "123"})
        with self.assertRaises(InventoryError) as raised:
            self.service.create({"name": "B", "barcode": "123"})
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.field, "barcode")

    def test_negative_or_non_finite_quantity_is_rejected(self) -> None:
        for quantity in (-1, "nan", "inf"):
            with self.subTest(quantity=quantity):
                with self.assertRaises(InventoryError):
                    self.service.create(
                        {"name": "Test", "tracking_mode": "exact", "quantity": quantity}
                    )

    def test_update_changes_only_explicitly_submitted_fields(self) -> None:
        item = self.service.create({"name": "Mehl", "tracking_mode": "exact", "quantity": 3})
        changed = self.service.update(item["id"], {"location": "Speisekammer"})
        self.assertEqual(changed["quantity"], 3)
        self.assertEqual(changed["location"], "Speisekammer")

    def test_switching_from_presence_to_counted_mode_keeps_stock_unknown(self) -> None:
        item = self.service.create({"name": "Dosenmais", "stock_status": "present"})
        changed = self.service.update(item["id"], {"tracking_mode": "exact"})
        self.assertEqual(changed["tracking_mode"], "exact")
        self.assertEqual(changed["stock_status"], "unknown")
        self.assertIsNone(changed["quantity"])

    def test_search_and_category_filter(self) -> None:
        self.service.create({"name": "Schraubendreher", "category": "Werkzeuge"})
        self.service.create({"name": "Milch", "category": "Lebensmittel"})
        self.assertEqual(len(self.service.list_items(search="SCHRAUB")), 1)
        self.assertEqual(
            [item["name"] for item in self.service.list_items(category="Werkzeuge")],
            ["Schraubendreher"],
        )

    def test_delete_and_missing_items(self) -> None:
        item = self.service.create({"name": "Test"})
        self.service.delete(item["id"])
        with self.assertRaises(InventoryError) as raised:
            self.service.get(item["id"])
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
