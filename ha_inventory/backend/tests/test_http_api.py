from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.app import create_handler
from backend.product_lookup.provider import (
    ProductCandidate,
    ProductLookupRateLimited,
    ProductLookupUnavailable,
)
from backend.product_lookup.service import ProductLookupService
from backend.web.handler import ingress_request_allowed


class HttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        handler = create_handler(
            Path(self.temp_dir.name), ingress_ip_check=False, product_providers=[]
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def request(
        self,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        headers: dict[str, str] | None = None,
    ):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read()), response.headers
        except HTTPError as error:
            return error.code, json.loads(error.read()), error.headers

    def test_create_list_lookup_update_and_delete(self) -> None:
        _, session, _ = self.request("/api/v1/write-session")
        write_headers = {"X-HA-Inventory-Write-Token": session["write_token"]}
        status, created, _ = self.request(
            "/api/v1/items", "POST", {"name": "Kichererbsen", "barcode": "00123"}, write_headers
        )
        self.assertEqual(status, 201)
        item_id = created["item"]["id"]

        status, looked_up, _ = self.request("/api/v1/items/by-barcode/00123")
        self.assertEqual(status, 200)
        self.assertEqual(looked_up["item"]["id"], item_id)
        self.assertIsNone(looked_up["item"]["quantity"])
        self.assertEqual(looked_up["item"]["stock_status"], "unknown")
        _, after_scan, _ = self.request(f"/api/v1/items/{item_id}")
        self.assertIsNone(after_scan["item"]["quantity"])

        status, listed, _ = self.request("/api/v1/items?search=Kicher")
        self.assertEqual(status, 200)
        self.assertEqual(len(listed["items"]), 1)

        status, updated, _ = self.request(
            f"/api/v1/items/{item_id}",
            "PATCH",
            {"location": "Vorratsschrank"},
            write_headers,
        )
        self.assertEqual(status, 200)
        self.assertIsNone(updated["item"]["quantity"])

        status, deleted, _ = self.request(f"/api/v1/items/{item_id}", "DELETE", headers=write_headers)
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])

    def test_health_and_frontend_are_served(self) -> None:
        status, health, headers = self.request("/api/v1/health")
        self.assertEqual((status, health["status"]), (200, "ok"))
        self.assertEqual(headers.get("X-HA-Inventory-API-Version"), "1")
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        with urlopen(self.base_url + "/", timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["Content-Type"])
            document = response.read()
            self.assertIn(b"Lager", document)
            self.assertIn(b"detail-dialog", document)
            self.assertIn(b"ZXing", document)
        with urlopen(self.base_url + "/stock.mjs", timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"stockLabel", response.read())
        with urlopen(self.base_url + "/vendor/zxing-browser.mjs", timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("javascript", response.headers["Content-Type"])
            self.assertGreater(int(response.headers["Content-Length"]), 100_000)

    def test_validation_error_is_json(self) -> None:
        _, session, _ = self.request("/api/v1/write-session")
        status, body, _ = self.request(
            "/api/v1/items", "POST", {"name": "  "},
            {"X-HA-Inventory-Write-Token": session["write_token"]},
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["field"], "name")

    def test_read_endpoints_return_catalog_facets_and_support_filters(self) -> None:
        _, session, _ = self.request("/api/v1/write-session")
        headers = {"X-HA-Inventory-Write-Token": session["write_token"]}
        for payload in (
            {"name": "Olivenöl", "category": "Lebensmittel", "location": "Speisekammer", "stock_status": "present"},
            {"name": "Hammer", "category": "Werkzeuge", "location": "Werkstatt", "tracking_mode": "exact", "quantity": 1, "stock_status": "known"},
        ):
            self.assertEqual(self.request("/api/v1/items", "POST", payload, headers)[0], 201)

        self.assertEqual(self.request("/api/v1/categories")[1]["categories"], ["Lebensmittel", "Werkzeuge"])
        self.assertEqual(self.request("/api/v1/locations")[1]["locations"], ["Speisekammer", "Werkstatt"])
        statuses = self.request("/api/v1/stock-statuses")[1]["stock_statuses"]
        self.assertIn({"value": "known", "label": "Menge erfasst"}, statuses)
        status, filtered, _ = self.request("/api/v1/items?location=Werkstatt&stock_status=known")
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in filtered["items"]], ["Hammer"])

    def test_mutations_require_a_write_session_and_get_requires_no_token(self) -> None:
        self.assertEqual(self.request("/api/v1/items")[0], 200)
        status, body, _ = self.request("/api/v1/items", "POST", {"name": "Blocked"})
        self.assertEqual(status, 403)
        self.assertIn("Schreibsitzung", body["error"])
        self.assertEqual(self.request("/api/items", "POST", {"name": "Legacy blocked"})[0], 403)

        _, session, _ = self.request("/api/v1/write-session")
        token = session["write_token"]
        status, created, _ = self.request(
            "/api/v1/items", "POST", {"name": "Freigegeben"},
            {"X-HA-Inventory-Write-Token": token},
        )
        self.assertEqual(status, 201)
        item_id = created["item"]["id"]
        status, _, _ = self.request(f"/api/v1/items/{item_id}", "DELETE")
        self.assertEqual(status, 403)
        status, _, _ = self.request(
            f"/api/v1/items/{item_id}", "DELETE",
            headers={"X-HA-Inventory-Write-Token": token},
        )
        self.assertEqual(status, 200)

    def test_item_id_is_independent_of_barcode_and_not_reused_after_delete(self) -> None:
        _, session, _ = self.request("/api/v1/write-session")
        headers = {"X-HA-Inventory-Write-Token": session["write_token"]}
        status, first, _ = self.request("/api/v1/items", "POST", {"name": "Artikel ohne Barcode"}, headers)
        self.assertEqual(status, 201)
        first_id = first["item"]["id"]
        self.assertIsNone(first["item"]["barcode"])

        status, updated, _ = self.request(
            f"/api/v1/items/{first_id}", "PATCH", {"barcode": "007700"}, headers
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["item"]["id"], first_id)
        self.assertEqual(self.request(f"/api/v1/items/{first_id}")[1]["item"]["barcode"], "007700")

        self.assertEqual(self.request(f"/api/v1/items/{first_id}", "DELETE", headers=headers)[0], 200)
        _, second, _ = self.request("/api/v1/items", "POST", {"name": "Nächster Artikel"}, headers)
        self.assertGreater(second["item"]["id"], first_id)

    def test_ingress_mode_rejects_direct_lan_requests(self) -> None:
        handler = self.server.RequestHandlerClass
        handler.require_ingress_proxy = True
        try:
            status, body, _ = self.request("/api/v1/health")
        finally:
            handler.require_ingress_proxy = False
        self.assertEqual(status, 403)
        self.assertIn("Ingress", body["error"])

    def test_ingress_gate_accepts_only_the_supervisor_proxy(self) -> None:
        self.assertTrue(ingress_request_allowed("172.30.32.2"))
        self.assertFalse(ingress_request_allowed("172.30.32.3"))
        self.assertTrue(ingress_request_allowed("127.0.0.1", required=False))

    def use_product_provider(self, provider) -> None:
        handler = self.server.RequestHandlerClass
        handler.product_lookup = ProductLookupService(handler.inventory, [provider])

    def test_product_lookup_checks_local_inventory_first_and_never_changes_stock(self) -> None:
        class ShouldNotBeCalled:
            name = "test-provider"

            def lookup(self, barcode):
                raise AssertionError("local barcode hit must not call providers")

        self.use_product_provider(ShouldNotBeCalled())
        _, session, _ = self.request("/api/v1/write-session")
        headers = {"X-HA-Inventory-Write-Token": session["write_token"]}
        status, created, _ = self.request(
            "/api/v1/items", "POST",
            {"name": "Schrauben", "barcode": "00042", "tracking_mode": "exact",
             "quantity": 6, "stock_status": "known"},
            headers,
        )
        self.assertEqual(status, 201)
        item_id = created["item"]["id"]
        status, result, _ = self.request("/api/v1/product-lookup/00042")
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "local")
        self.assertEqual(result["item"]["id"], item_id)
        current = self.request(f"/api/v1/items/{item_id}")[1]["item"]
        self.assertEqual(current["quantity"], 6)
        self.assertEqual(current["stock_status"], "known")

    def test_alphanumeric_item_code_is_found_and_unknown_code_skips_external_provider(self) -> None:
        class ShouldNotBeCalled:
            name = "numeric-provider"

            def lookup(self, _barcode):
                raise AssertionError("non-numeric codes must not be sent to Open Facts")

        self.use_product_provider(ShouldNotBeCalled())
        _, session, _ = self.request("/api/v1/write-session")
        headers = {"X-HA-Inventory-Write-Token": session["write_token"]}
        status, created, _ = self.request(
            "/api/v1/items", "POST",
            {"name": "Akkuschrauber", "barcode": "TOOL-001", "tracking_mode": "exact",
             "quantity": 3, "stock_status": "known"},
            headers,
        )
        self.assertEqual(status, 201)
        item_id = created["item"]["id"]

        status, found, _ = self.request("/api/v1/product-lookup/TOOL-001")
        self.assertEqual(status, 200)
        self.assertEqual(found["status"], "local")
        self.assertEqual(found["item"]["id"], item_id)
        self.assertEqual(found["item"]["barcode"], "TOOL-001")

        status, unknown, _ = self.request("/api/v1/product-lookup/TOOL-002")
        self.assertEqual(status, 200)
        self.assertEqual(unknown, {"status": "not_found", "barcode": "TOOL-002"})
        current = self.request(f"/api/v1/items/{item_id}")[1]["item"]
        self.assertEqual(current["quantity"], 3)
        self.assertEqual(current["stock_status"], "known")

    def test_rate_limited_lookup_returns_bounded_retry_guidance(self) -> None:
        class RateLimited:
            name = "rate-limited"

            def lookup(self, _barcode):
                raise ProductLookupRateLimited("Warte kurz", retry_after_seconds=4.1)

        self.use_product_provider(RateLimited())
        status, body, headers = self.request("/api/v1/product-lookup/00088")
        self.assertEqual(status, 429)
        self.assertEqual(body["code"], "product_lookup_rate_limited")
        self.assertEqual(body["status"], "rate_limited")
        self.assertAlmostEqual(body["retry_after_seconds"], 4.1)
        self.assertEqual(headers.get("Retry-After"), "5")
        self.assertEqual(self.request("/api/v1/items")[0], 200)

    def test_external_product_lookup_returns_suggestions_without_saving(self) -> None:
        class Provider:
            name = "test-provider"
            calls = 0

            def lookup(self, barcode):
                self.calls += 1
                return ProductCandidate(
                    barcode=barcode, name="Haferdrink", brand="Beispiel", product_size="1 l",
                    category="Lebensmittel", image_url="https://images.openfoodfacts.org/p.jpg",
                    image_license="CC BY-SA",
                    data_source="Open Food Facts",
                    source_url=f"https://world.openfoodfacts.org/product/{barcode}",
                )

        provider = Provider()
        self.use_product_provider(provider)
        status, result, _ = self.request("/api/v1/product-lookup/000123")
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "identified")
        self.assertEqual(result["product"]["barcode"], "000123")
        self.assertEqual(result["product"]["name"], "Haferdrink")
        self.assertEqual(result["product"]["brand"], "Beispiel")
        self.assertEqual(result["product"]["product_size"], "1 l")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.request("/api/v1/items")[1]["items"], [])

    def test_not_found_and_unavailable_lookup_leave_local_api_usable(self) -> None:
        class NotFound:
            name = "not-found"

            def lookup(self, barcode):
                return None

        self.use_product_provider(NotFound())
        status, missing, _ = self.request("/api/v1/product-lookup/0099")
        self.assertEqual((status, missing["status"]), (200, "not_found"))
        self.assertEqual(self.request("/api/v1/items")[0], 200)

        class Unavailable:
            name = "offline"

            def lookup(self, barcode):
                raise ProductLookupUnavailable("timeout")

        self.use_product_provider(Unavailable())
        status, error, _ = self.request("/api/v1/product-lookup/0099")
        self.assertEqual(status, 503)
        self.assertEqual(error["status"], "unavailable")
        self.assertEqual(self.request("/api/v1/items")[0], 200)

    def test_lookup_rejects_invalid_barcode_and_remains_ingress_protected(self) -> None:
        status, error, _ = self.request(f"/api/v1/product-lookup/{'x' * 65}")
        self.assertEqual(status, 400)
        self.assertEqual(error["field"], "barcode")
        handler = self.server.RequestHandlerClass
        handler.require_ingress_proxy = True
        try:
            status, body, _ = self.request("/api/v1/product-lookup/0001")
        finally:
            handler.require_ingress_proxy = False
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "ingress_required")

    def test_expired_write_session_has_specific_error_and_does_not_mutate(self) -> None:
        _, session, _ = self.request("/api/v1/write-session")
        handler = self.server.RequestHandlerClass
        handler.write_tokens[session["write_token"]] = 0
        status, body, _ = self.request(
            "/api/v1/items", "POST", {"name": "Noch nicht gespeichert"},
            {"X-HA-Inventory-Write-Token": session["write_token"]},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "write_session_invalid")
        self.assertEqual(self.request("/api/v1/items")[1]["items"], [])

    def test_movement_api_requires_ingress_write_session_and_returns_history(self) -> None:
        _, session, _ = self.request("/api/v1/write-session")
        headers = {"X-HA-Inventory-Write-Token": session["write_token"]}
        status, created, _ = self.request(
            "/api/v1/items", "POST",
            {"name": "Milch", "barcode": "000123", "tracking_mode": "exact", "quantity": 2},
            headers,
        )
        item_id = created["item"]["id"]
        payload = {"action": "receive", "quantity": 2, "idempotency_key": "http-book-1"}
        self.assertEqual(self.request(f"/api/v1/items/{item_id}/movements", "POST", payload)[0], 403)
        status, booked, _ = self.request(
            f"/api/v1/items/{item_id}/movements", "POST", payload, headers
        )
        self.assertEqual(status, 201)
        self.assertEqual(booked["movement"]["quantity_after"], 4)
        handler = self.server.RequestHandlerClass
        handler.require_ingress_proxy = True
        try:
            denied_ingress, ingress_body, _ = self.request(
                f"/api/v1/items/{item_id}/movements", "POST",
                {"action": "consume", "quantity": 1, "idempotency_key": "direct-path"}, headers,
            )
        finally:
            handler.require_ingress_proxy = False
        self.assertEqual((denied_ingress, ingress_body["code"]), (403, "ingress_required"))
        self.assertEqual(self.request(f"/api/v1/items/{item_id}")[1]["item"]["quantity"], 4)
        status, replayed, _ = self.request(
            f"/api/v1/items/{item_id}/movements", "POST", payload, headers
        )
        self.assertEqual(status, 200)
        self.assertEqual(replayed["movement"]["id"], booked["movement"]["id"])
        history_status, history, _ = self.request(f"/api/v1/items/{item_id}/movements")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history["movements"]), 1)

        undo_status, undone, _ = self.request(
            f"/api/v1/movements/{booked['movement']['id']}/undo", "POST",
            {"idempotency_key": "http-undo-1"}, headers,
        )
        self.assertEqual(undo_status, 201)
        self.assertEqual(undone["movement"]["action"], "undo")
        history = self.request(f"/api/v1/items/{item_id}/movements")[1]["movements"]
        original = next(entry for entry in history if entry["id"] == booked["movement"]["id"])
        self.assertEqual(original["undone_by_movement_id"], undone["movement"]["id"])

        handler.write_tokens[session["write_token"]] = 0
        denied, body, _ = self.request(
            f"/api/v1/items/{item_id}/movements", "POST",
            {"action": "consume", "quantity": 1, "idempotency_key": "expired-book"},
            {"X-HA-Inventory-Write-Token": session["write_token"]},
        )
        self.assertEqual((denied, body["code"]), (403, "write_session_invalid"))
        self.assertEqual(self.request(f"/api/v1/items/{item_id}")[1]["item"]["quantity"], 2)

    def test_extremely_large_movement_quantity_returns_validation_error_without_mutation(self) -> None:
        _, session, _ = self.request("/api/v1/write-session")
        headers = {"X-HA-Inventory-Write-Token": session["write_token"]}
        _, created, _ = self.request(
            "/api/v1/items", "POST",
            {"name": "Schwerlast", "tracking_mode": "exact", "quantity": 2}, headers,
        )
        item_id = created["item"]["id"]
        status, body, _ = self.request(
            f"/api/v1/items/{item_id}/movements", "POST",
            {"action": "receive", "quantity": 1 << 100, "idempotency_key": "http-huge-quantity"},
            headers,
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["field"], "quantity")
        self.assertEqual(self.request(f"/api/v1/items/{item_id}")[1]["item"]["quantity"], 2)
        self.assertEqual(self.request(f"/api/v1/items/{item_id}/movements")[1]["movements"], [])

    def test_database_survives_a_server_restart(self) -> None:
        _, session, _ = self.request("/api/v1/write-session")
        status, created, _ = self.request(
            "/api/v1/items",
            "POST",
            {
                "name": "Persistenter Artikel",
                "barcode": "0099",
                "tracking_mode": "exact",
                "quantity": 5,
                "stock_status": "known",
            },
            {"X-HA-Inventory-Write-Token": session["write_token"]},
        )
        self.assertEqual(status, 201)
        item_id = created["item"]["id"]

        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

        handler = create_handler(
            Path(self.temp_dir.name), ingress_ip_check=False, product_providers=[]
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

        status, restored, _ = self.request(f"/api/v1/items/{item_id}")
        self.assertEqual(status, 200)
        self.assertEqual(restored["item"]["quantity"], 5)
        self.assertEqual(restored["item"]["stock_status"], "known")


if __name__ == "__main__":
    unittest.main()
