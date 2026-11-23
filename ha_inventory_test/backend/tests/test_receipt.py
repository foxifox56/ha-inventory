from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.database import Database
from backend.errors import InventoryError
from backend.inventory.movements import StockMovementService
from backend.inventory.repository import InventoryRepository
from backend.inventory.service import InventoryService
from backend.receipt.image_processing import MAX_IMAGE_BYTES, prepare_image
from backend.receipt.ocr import OCRLine, OCRResult, TesseractEngine
from backend.receipt.parsing import parse_receipt
from backend.receipt.service import ReceiptService


class StaticOCR:
    def __init__(self, lines: list[str], language: str = "deu"):
        self.lines = lines
        self.language = language

    def recognize(self, _image: bytes, _content_type: str) -> OCRResult:
        return OCRResult(
            text="\n".join(self.lines),
            lines=tuple(OCRLine(line, 0.98) for line in self.lines),
            languages=(self.language, "eng"),
        )


class ReceiptServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name))
        self.database.initialize()
        self.inventory = InventoryService(InventoryRepository(self.database))
        self.movements = StockMovementService(self.database)
        self.ocr = StaticOCR([
            "REWE", "2 x MILCH 1,09 2,18", "HAFERDRINK 1,49", "SUMME 3,67",
        ])
        self.receipts = ReceiptService(self.database, self.inventory, self.movements, self.ocr)
        self.image = b"synthetic-image-bytes"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def recognize(self):
        return self.receipts.recognize(self.image, "image/png")

    @staticmethod
    def payload(receipt, milk_id: int, *, key="import-1", allow_duplicate=False):
        milk = next(line for line in receipt["lines"] if "MILCH" in line["label"].upper())
        oat = next(line for line in receipt["lines"] if "HAFERDRINK" in line["label"].upper())
        return {
            "confirmed": True,
            "idempotency_key": key,
            "allow_duplicate": allow_duplicate,
            "rows": [
                {"line_ids": milk["line_ids"], "label": milk["label"], "decision": "existing",
                 "item_id": milk_id, "quantity": milk["quantity"], "tracking_mode": "exact",
                 "learn_alias": True},
                {"line_ids": oat["line_ids"], "label": oat["label"], "decision": "new",
                 "name": "Haferdrink", "barcode": "", "category": "Lebensmittel",
                 "location": "Vorratsschrank", "unit": "Packung", "tracking_mode": "inventory",
                 "quantity": oat["quantity"], "learn_alias": False},
            ],
        }

    def test_rewe_parser_reads_explicit_multipliers_and_does_not_treat_prices_as_counts(self) -> None:
        parsed = parse_receipt([
            OCRLine("REWE", .99), OCRLine("2 x MILCH 1,09 2,18", .99),
            OCRLine("BANANEN 1,49", .99), OCRLine("PFAND 0,25", .99),
            OCRLine("SUMME 3,92", .99),
        ])
        self.assertEqual(parsed.merchant, "rewe")
        self.assertEqual([line["label"] for line in parsed.lines], ["MILCH", "BANANEN"])
        self.assertEqual([line["quantity"] for line in parsed.lines], [2, 1])
        self.assertEqual(parsed.ignored_line_count, 3)

    def test_rewe_split_multiplier_after_priced_product_line_updates_quantity(self) -> None:
        parsed = parse_receipt([
            OCRLine("REWE", .99), OCRLine("MILCH 1,09", .99),
            OCRLine("2 x 1,09 2,18", .99), OCRLine("SUMME 2,18", .99),
        ])
        self.assertEqual([(row["label"], row["quantity"]) for row in parsed.lines], [("MILCH", 2)])
        self.assertFalse(parsed.lines[0]["requires_review"])

    def test_kaufland_split_multiplier_supports_price_absent_and_present_product_rows(self) -> None:
        parsed = parse_receipt([
            OCRLine("KAUFLAND", .99), OCRLine("BIO JOGHURT", .99), OCRLine("2 x 0,89 1,78", .99),
            OCRLine("HAFERDRINK 1,49", .99), OCRLine("3 STK", .99),
            OCRLine("BANANEN 1,29", .99), OCRLine("2 x 1,29", .99),
            OCRLine("SUMME 7,14", .99),
        ])
        self.assertEqual([row["quantity"] for row in parsed.lines], [2, 3, 2])
        self.assertEqual([row["label"] for row in parsed.lines], ["BIO JOGHURT", "HAFERDRINK", "BANANEN"])
        self.assertEqual([row["requires_review"] for row in parsed.lines], [False, False, False])

    def test_split_multiplier_after_discount_or_deposit_is_reviewed(self) -> None:
        for interruption in ("RABATT -0,10", "PFAND 0,25", "-0,10"):
            with self.subTest(interruption=interruption):
                parsed = parse_receipt([
                    OCRLine("REWE", .99), OCRLine("MILCH 1,09", .99),
                    OCRLine(interruption, .99), OCRLine("2 x 1,09 2,18", .99),
                    OCRLine("SUMME 2,18", .99),
                ])
                self.assertEqual(len(parsed.lines), 1)
                self.assertEqual(parsed.lines[0]["quantity"], 2)
                self.assertTrue(parsed.lines[0]["requires_review"])

    def test_currency_amounts_are_never_used_as_counts_and_bare_multiplier_needs_review(self) -> None:
        parsed = parse_receipt([
            OCRLine("KAUFLAND", .99), OCRLine("KÄSE 2,99", .99),
            OCRLine("SAFT 1,49", .99), OCRLine("2 x", .99),
        ])
        self.assertEqual([(row["label"], row["quantity"]) for row in parsed.lines], [("KÄSE", 1), ("SAFT", 2)])
        self.assertTrue(parsed.lines[1]["requires_review"])

    def test_kaufland_store_lines_discounts_returns_and_payment_are_ignored(self) -> None:
        parsed = parse_receipt([
            OCRLine("KAUFLAND", .99), OCRLine("BIO JOGHURT 0,89", .99),
            OCRLine("- RABATT 0,10", .99), OCRLine("PFAND-RÜCKGABE 0,25", .99),
            OCRLine("EC-KARTE 1,00", .99), OCRLine("ZU ZAHLEN 0,64", .99),
        ])
        self.assertEqual(parsed.merchant, "kaufland")
        self.assertEqual([line["label"] for line in parsed.lines], ["BIO JOGHURT"])
        self.assertEqual(parsed.lines[0]["quantity"], 1)

    def test_unknown_merchant_uses_generic_parser_and_marks_unpriced_quantity_uncertain(self) -> None:
        parsed = parse_receipt([
            OCRLine("SAUERTEIGBROT 2,40", .99), OCRLine("LOSE TOMATEN", .62),
        ])
        self.assertEqual(parsed.merchant, "other")
        self.assertEqual(parsed.lines[0]["quantity"], 1)
        self.assertIsNone(parsed.lines[1]["quantity"])
        self.assertTrue(parsed.lines[1]["requires_review"])

    def test_recognition_matches_catalog_but_never_changes_items_or_stock(self) -> None:
        milk = self.inventory.create({"name": "Milch", "tracking_mode": "exact", "quantity": 4})
        recognized = self.recognize()
        self.assertEqual(recognized["merchant"], "rewe")
        self.assertEqual(len(recognized["lines"]), 2)
        self.assertEqual(recognized["lines"][0]["quantity"], 2)
        self.assertEqual(recognized["lines"][0]["item_id"], milk["id"])
        self.assertEqual(recognized["ignored_line_count"], 2)
        self.assertEqual(self.inventory.get(milk["id"])["quantity"], 4)
        self.assertEqual(len(self.movements.list_for_item(milk["id"])), 0)
        connection = self.database.connect()
        try:
            receipt = connection.execute("SELECT * FROM receipt_imports WHERE id = ?", (recognized["receipt_id"],)).fetchone()
            self.assertIsNotNone(receipt)
            self.assertNotIn("ocr_text", receipt.keys())
            self.assertNotIn("image", receipt.keys())
            self.assertEqual(receipt["line_count"], 3)
        finally:
            connection.close()

    def test_import_is_atomic_idempotent_learns_aliases_and_bulk_undo_restores_initial_stock(self) -> None:
        milk = self.inventory.create({"name": "Milch", "tracking_mode": "exact", "quantity": 4})
        recognized = self.recognize()
        payload = self.payload(recognized, milk["id"])
        result = self.receipts.import_receipt(recognized["receipt_id"], payload)
        self.assertEqual(len(result["movements"]), 2)
        self.assertEqual(self.inventory.get(milk["id"])["quantity"], 6)
        new_item = next(item for item in self.inventory.list_items() if item["name"] == "Haferdrink")
        self.assertEqual(new_item["quantity"], 1)
        self.assertEqual(new_item["tracking_mode"], "inventory")
        self.assertEqual({movement["source"] for movement in result["movements"]}, {"receipt"})
        self.assertTrue(all(movement["receipt_import_id"] == recognized["receipt_id"] for movement in result["movements"]))

        replay = self.receipts.import_receipt(recognized["receipt_id"], payload)
        self.assertTrue(replay["replayed"])
        self.assertEqual(len(self.movements.list_for_item(milk["id"])), 1)
        with self.assertRaises(InventoryError) as conflict:
            self.receipts.import_receipt(recognized["receipt_id"], self.payload(recognized, milk["id"], key="different", allow_duplicate=True))
        self.assertEqual(conflict.exception.status_code, 409)

        second_recognition = self.recognize()
        self.assertEqual(second_recognition["lines"][0]["match_source"], "merchant_alias")
        self.assertEqual(second_recognition["lines"][0]["item_id"], milk["id"])
        undone = self.receipts.undo_receipt(recognized["receipt_id"], {
            "confirmed": True, "idempotency_key": "undo-import-1",
        })
        self.assertEqual(len(undone["movements"]), 2)
        self.assertEqual(self.inventory.get(milk["id"])["quantity"], 4)
        restored_new = self.inventory.get(new_item["id"])
        self.assertIsNone(restored_new["quantity"])
        self.assertEqual(restored_new["tracking_mode"], "simple")
        connection = self.database.connect()
        try:
            retained_alias = connection.execute(
                "SELECT item_id FROM receipt_product_aliases WHERE merchant = 'rewe' AND normalized_alias = 'milch'"
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(retained_alias)
        self.assertEqual(retained_alias["item_id"], milk["id"])
        replay_undo = self.receipts.undo_receipt(recognized["receipt_id"], {
            "confirmed": True, "idempotency_key": "undo-import-1",
        })
        self.assertTrue(replay_undo["replayed"])

    def test_second_import_detects_duplicate_and_requires_explicit_override(self) -> None:
        milk = self.inventory.create({"name": "Milch", "tracking_mode": "exact", "quantity": 4})
        first = self.recognize()
        self.receipts.import_receipt(first["receipt_id"], self.payload(first, milk["id"]))
        second = self.recognize()
        self.assertTrue(second["duplicate_warning"])
        with self.assertRaises(InventoryError) as duplicate:
            self.receipts.import_receipt(second["receipt_id"], self.payload(second, milk["id"], key="import-2"))
        self.assertEqual(duplicate.exception.code, "receipt_duplicate")
        imported = self.receipts.import_receipt(
            second["receipt_id"], self.payload(second, milk["id"], key="import-2", allow_duplicate=True)
        )
        self.assertFalse(imported["replayed"])
        self.assertEqual(self.inventory.get(milk["id"])["quantity"], 8)

    def test_later_consumption_causes_all_or_nothing_bulk_undo(self) -> None:
        milk = self.inventory.create({"name": "Milch", "tracking_mode": "exact", "quantity": 4})
        recognized = self.recognize()
        self.receipts.import_receipt(recognized["receipt_id"], self.payload(recognized, milk["id"]))
        new_item = next(item for item in self.inventory.list_items() if item["name"] == "Haferdrink")
        self.movements.book(milk["id"], {"action": "consume", "quantity": 6, "idempotency_key": "consume-later"})
        with self.assertRaises(InventoryError):
            self.receipts.undo_receipt(recognized["receipt_id"], {"confirmed": True, "idempotency_key": "undo-would-underflow"})
        self.assertEqual(self.inventory.get(milk["id"])["quantity"], 0)
        self.assertEqual(self.inventory.get(new_item["id"])["quantity"], 1)
        self.assertEqual(self.receipts.get_receipt(recognized["receipt_id"])["receipt"]["status"], "imported")
        self.assertEqual(len([row for row in self.movements.list_for_item(new_item["id"]) if row["action"] == "undo"]), 0)

    def test_unconfirmed_import_and_extreme_or_invalid_quantities_do_not_mutate(self) -> None:
        milk = self.inventory.create({"name": "Milch", "tracking_mode": "exact", "quantity": 4})
        recognized = self.recognize()
        payload = self.payload(recognized, milk["id"])
        payload["confirmed"] = False
        with self.assertRaises(InventoryError):
            self.receipts.import_receipt(recognized["receipt_id"], payload)
        payload["confirmed"] = True
        payload["rows"][0]["quantity"] = 1 << 100
        with self.assertRaises(InventoryError):
            self.receipts.import_receipt(recognized["receipt_id"], payload)
        payload["rows"][0]["quantity"] = None
        with self.assertRaises(InventoryError):
            self.receipts.import_receipt(recognized["receipt_id"], payload)
        payload["rows"][0]["quantity"] = 0
        with self.assertRaises(InventoryError):
            self.receipts.import_receipt(recognized["receipt_id"], payload)
        self.assertEqual(self.inventory.get(milk["id"])["quantity"], 4)
        self.assertEqual(len(self.movements.list_for_item(milk["id"])), 0)

    def test_partial_alias_conflict_rolls_back_created_items_and_movements(self) -> None:
        milk = self.inventory.create({"name": "Milch", "tracking_mode": "exact", "quantity": 4})
        alias_owner = self.inventory.create({"name": "Andere Milch", "tracking_mode": "exact", "quantity": 1})
        connection = self.database.connect()
        try:
            connection.execute(
                """INSERT INTO receipt_product_aliases
                   (merchant, normalized_alias, alias_text, item_id, created_at, updated_at)
                   VALUES ('rewe', 'milch', 'MILCH', ?, 'now', 'now')""", (alias_owner["id"],)
            )
            connection.commit()
        finally:
            connection.close()
        recognized = self.recognize()
        payload = self.payload(recognized, milk["id"])
        payload["rows"][0]["replace_alias"] = False
        with self.assertRaises(InventoryError):
            self.receipts.import_receipt(recognized["receipt_id"], payload)
        self.assertFalse(any(item["name"] == "Haferdrink" for item in self.inventory.list_items()))
        self.assertEqual(self.inventory.get(milk["id"])["quantity"], 4)
        self.assertEqual(len(self.movements.list_for_item(milk["id"])), 0)

    def test_image_processing_accepts_real_png_and_rejects_wrong_type_and_oversize(self) -> None:
        image = Image.new("RGB", (120, 240), "white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        prepared = prepare_image(buffer.getvalue(), "image/png")
        self.assertTrue(prepared.startswith(b"\x89PNG\r\n\x1a\n"))
        with self.assertRaises(InventoryError):
            prepare_image(buffer.getvalue(), "image/jpeg")
        with self.assertRaises(InventoryError) as large:
            prepare_image(b"x" * (MAX_IMAGE_BYTES + 1), "image/png")
        self.assertEqual(large.exception.status_code, 413)

    def test_tesseract_timeout_is_bounded_and_becomes_a_recoverable_error(self) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (100, 200), "white").save(buffer, format="PNG")
        engine = TesseractEngine(timeout_seconds=0.01)
        engine._languages = ("deu", "eng")
        with patch(
            "backend.receipt.ocr.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="tesseract", timeout=0.01),
        ):
            with self.assertRaises(InventoryError) as raised:
                engine.recognize(buffer.getvalue(), "image/png")
        self.assertEqual(raised.exception.status_code, 504)
        self.assertIn("zu lange", raised.exception.message)

    def test_tesseract_without_supported_language_data_fails_cleanly(self) -> None:
        engine = TesseractEngine()
        completed = subprocess.CompletedProcess(
            args=["tesseract", "--list-langs"], returncode=0,
            stdout='List of available languages in "tessdata" (1):\nosd\n',
        )
        with patch("backend.receipt.ocr.subprocess.run", return_value=completed):
            with self.assertRaises(InventoryError) as raised:
                engine.available_languages()
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("keine deutsche oder englische", raised.exception.message)


if __name__ == "__main__":
    unittest.main()
