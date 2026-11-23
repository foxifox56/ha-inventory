from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.database import Database
from backend.errors import InventoryError
from backend.inventory.movements import StockMovementService
from backend.inventory.repository import InventoryRepository
from backend.inventory.service import InventoryService


class StockMovementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name))
        self.database.initialize()
        self.inventory = InventoryService(InventoryRepository(self.database))
        self.movements = StockMovementService(self.database)
        self.item = self.inventory.create({
            "name": "Milch", "barcode": "000123", "tracking_mode": "exact", "quantity": 4,
        })

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def book(self, action: str, quantity: int, key: str, **kwargs):
        return self.movements.book(self.item["id"], {
            "action": action, "quantity": quantity, "idempotency_key": key, **kwargs,
        })

    def test_receive_consume_and_idempotent_replay_write_one_audited_change(self) -> None:
        received = self.book("receive", 3, "scan-1", source="barcode")
        self.assertEqual((received["quantity_before"], received["quantity_after"]), (4, 7))
        replay = self.book("receive", 3, "scan-1", source="barcode")
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["id"], received["id"])
        consumed = self.book("consume", 2, "scan-2", source="barcode")
        self.assertEqual((consumed["delta_quantity"], consumed["quantity_after"]), (-2, 5))
        self.assertEqual(self.inventory.get(self.item["id"])["quantity"], 5)
        self.assertEqual(len(self.movements.list_for_item(self.item["id"])), 2)

    def test_retry_after_lost_success_response_replays_without_a_second_booking(self) -> None:
        # The first call represents a commit whose HTTP response never reached
        # the client. Its retry must use that request's original key.
        committed = self.book("receive", 2, "lost-response-key", source="barcode")
        retry = self.book("receive", 2, "lost-response-key", source="barcode")
        self.assertEqual(retry["id"], committed["id"])
        self.assertTrue(retry["replayed"])
        self.assertEqual(self.inventory.get(self.item["id"])["quantity"], 6)
        self.assertEqual(len(self.movements.list_for_item(self.item["id"])), 1)

    def test_idempotency_key_cannot_be_reused_for_another_booking(self) -> None:
        self.book("receive", 1, "same")
        with self.assertRaises(InventoryError) as raised:
            self.book("consume", 1, "same")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.inventory.get(self.item["id"])["quantity"], 5)

    def test_concurrent_scans_cannot_overdraw_the_same_last_unit(self) -> None:
        item = self.inventory.create({"name": "Einzeldose", "tracking_mode": "exact", "quantity": 1})

        def consume(key: str):
            try:
                self.movements.book(item["id"], {
                    "action": "consume", "quantity": 1, "idempotency_key": key, "source": "barcode",
                })
                return "booked"
            except InventoryError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(consume, ("parallel-1", "parallel-2")))
        self.assertEqual(sorted(results), ["booked", "rejected"])
        self.assertEqual(self.inventory.get(item["id"])["quantity"], 0)
        self.assertEqual(len(self.movements.list_for_item(item["id"])), 1)

    def test_direct_quantity_edit_is_rejected_in_favor_of_movement_api(self) -> None:
        with self.assertRaises(InventoryError) as raised:
            self.inventory.update(self.item["id"], {"quantity": 99})
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.inventory.get(self.item["id"])["quantity"], 4)

    def test_negative_stock_and_unknown_stock_are_rejected(self) -> None:
        with self.assertRaises(InventoryError) as raised:
            self.book("consume", 5, "too-many")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.inventory.get(self.item["id"])["quantity"], 4)
        unknown = self.inventory.create({"name": "Kaffee", "barcode": "A-1"})
        with self.assertRaises(InventoryError):
            self.movements.book(unknown["id"], {
                "action": "receive", "quantity": 1, "idempotency_key": "no-baseline",
            })

    def test_movements_accept_only_positive_whole_pack_counts(self) -> None:
        for index, quantity in enumerate((0, -1, 1.5, True, "2")):
            with self.subTest(quantity=quantity), self.assertRaises(InventoryError):
                self.book("receive", quantity, f"invalid-{index}")
        self.assertEqual(self.inventory.get(self.item["id"])["quantity"], 4)

    def test_initial_stock_requires_explicit_confirmation_and_can_be_undone(self) -> None:
        unknown = self.inventory.create({"name": "Reis", "tracking_mode": "inventory"})
        payload = {
            "action": "initialize", "quantity": 6, "tracking_mode": "exact",
            "idempotency_key": "initial-1", "confirm_initial_stock": True,
        }
        without_confirmation = dict(payload, confirm_initial_stock=False, idempotency_key="initial-no")
        with self.assertRaises(InventoryError):
            self.movements.book(unknown["id"], without_confirmation)
        initial = self.movements.book(unknown["id"], payload)
        self.assertEqual(self.inventory.get(unknown["id"])["quantity"], 6)
        undone = self.movements.undo(initial["id"], {"idempotency_key": "undo-initial"})
        self.assertEqual(undone["action"], "undo")
        restored = self.inventory.get(unknown["id"])
        self.assertIsNone(restored["quantity"])
        self.assertEqual(restored["tracking_mode"], "inventory")
        with self.assertRaises(InventoryError):
            self.movements.undo(initial["id"], {"idempotency_key": "undo-initial-again"})

    def test_confirmed_zero_is_a_known_baseline_and_can_be_undone(self) -> None:
        unknown = self.inventory.create({"name": "Leerer Behälter", "tracking_mode": "inventory"})
        initial = self.movements.book(unknown["id"], {
            "action": "initialize", "quantity": 0, "tracking_mode": "exact",
            "idempotency_key": "zero-initial", "confirm_initial_stock": True,
        })
        item = self.inventory.get(unknown["id"])
        self.assertEqual((item["quantity"], item["stock_status"], item["tracking_mode"]), (0, "known", "exact"))
        self.assertEqual(initial["delta_quantity"], 0)
        with self.assertRaises(InventoryError):
            self.movements.book(unknown["id"], {
                "action": "consume", "quantity": 1, "idempotency_key": "zero-consume",
            })
        with self.assertRaises(InventoryError):
            self.movements.book(unknown["id"], {
                "action": "receive", "quantity": 0, "idempotency_key": "zero-receive",
            })

        receive = self.movements.book(unknown["id"], {
            "action": "receive", "quantity": 1, "idempotency_key": "from-zero",
        })
        self.movements.undo(receive["id"], {"idempotency_key": "undo-from-zero"})
        undone = self.movements.undo(initial["id"], {"idempotency_key": "undo-zero-initial"})
        self.assertEqual(undone["delta_quantity"], 0)
        restored = self.inventory.get(unknown["id"])
        self.assertIsNone(restored["quantity"])
        self.assertEqual(restored["stock_status"], "unknown")
        self.assertEqual(restored["tracking_mode"], "inventory")

    def test_initial_stock_undo_rejects_live_later_movements_with_zero_net_delta(self) -> None:
        unknown = self.inventory.create({"name": "Bohnen", "tracking_mode": "inventory"})
        initial = self.movements.book(unknown["id"], {
            "action": "initialize", "quantity": 3, "tracking_mode": "exact",
            "idempotency_key": "live-initial", "confirm_initial_stock": True,
        })
        self.movements.book(unknown["id"], {"action": "receive", "quantity": 2, "idempotency_key": "live-receive"})
        self.movements.book(unknown["id"], {"action": "consume", "quantity": 2, "idempotency_key": "live-consume"})
        self.assertEqual(self.inventory.get(unknown["id"])["quantity"], 3)
        with self.assertRaises(InventoryError) as raised:
            self.movements.undo(initial["id"], {"idempotency_key": "live-undo-initial"})
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.inventory.get(unknown["id"])["quantity"], 3)

    def test_initial_stock_undo_allows_fully_reversed_later_movements_and_reinitialization(self) -> None:
        unknown = self.inventory.create({"name": "Linsen", "tracking_mode": "inventory"})
        initial = self.movements.book(unknown["id"], {
            "action": "initialize", "quantity": 3, "tracking_mode": "exact",
            "idempotency_key": "reversed-initial", "confirm_initial_stock": True,
        })
        receive = self.movements.book(unknown["id"], {
            "action": "receive", "quantity": 2, "idempotency_key": "reversed-receive",
        })
        consume = self.movements.book(unknown["id"], {
            "action": "consume", "quantity": 1, "idempotency_key": "reversed-consume",
        })
        self.movements.undo(consume["id"], {"idempotency_key": "reversed-undo-consume"})
        self.movements.undo(receive["id"], {"idempotency_key": "reversed-undo-receive"})
        self.assertEqual(self.inventory.get(unknown["id"])["quantity"], 3)
        self.movements.undo(initial["id"], {"idempotency_key": "reversed-undo-initial"})
        self.assertIsNone(self.inventory.get(unknown["id"])["quantity"])
        next_initial = self.movements.book(unknown["id"], {
            "action": "initialize", "quantity": 4, "tracking_mode": "inventory",
            "idempotency_key": "reinitialize", "confirm_initial_stock": True,
        })
        self.assertEqual(next_initial["quantity_after"], 4)
        self.assertEqual(self.inventory.get(unknown["id"])["quantity"], 4)

    def test_undo_is_exactly_once_and_never_creates_negative_stock(self) -> None:
        receive = self.book("receive", 2, "receive-1")
        self.book("consume", 5, "consume-2") if False else None
        undone = self.movements.undo(receive["id"], {"idempotency_key": "undo-1"})
        self.assertEqual(undone["quantity_after"], 4)
        replay = self.movements.undo(receive["id"], {"idempotency_key": "undo-1"})
        self.assertTrue(replay["replayed"])
        with self.assertRaises(InventoryError) as raised:
            self.movements.undo(receive["id"], {"idempotency_key": "undo-2"})
        self.assertEqual(raised.exception.status_code, 409)

        receive_again = self.book("receive", 2, "receive-3")
        later_consume = self.book("consume", 5, "consume-4")
        with self.assertRaises(InventoryError):
            self.movements.undo(receive_again["id"], {"idempotency_key": "undo-too-low"})
        self.movements.undo(later_consume["id"], {"idempotency_key": "undo-later"})
        self.movements.undo(receive_again["id"], {"idempotency_key": "undo-after-later"})
        self.assertEqual(self.inventory.get(self.item["id"])["quantity"], 4)

    def test_delete_is_blocked_when_it_would_orphan_movement_history(self) -> None:
        movement = self.book("receive", 1, "keep-history")
        self.assertIsNotNone(movement)
        with self.assertRaises(InventoryError) as raised:
            self.inventory.delete(self.item["id"])
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(len(self.movements.list_for_item(self.item["id"])), 1)


if __name__ == "__main__":
    unittest.main()
