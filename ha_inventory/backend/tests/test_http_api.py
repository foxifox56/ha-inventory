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


class HttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        handler = create_handler(Path(self.temp_dir.name), ingress_ip_check=False)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def request(self, path: str, method: str = "GET", body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read()), response.headers
        except HTTPError as error:
            return error.code, json.loads(error.read()), error.headers

    def test_create_list_lookup_update_and_delete(self) -> None:
        status, created, _ = self.request(
            "/api/items", "POST", {"name": "Kichererbsen", "barcode": "00123"}
        )
        self.assertEqual(status, 201)
        item_id = created["item"]["id"]

        status, looked_up, _ = self.request("/api/items/barcode/00123")
        self.assertEqual(status, 200)
        self.assertEqual(looked_up["item"]["id"], item_id)
        self.assertEqual(looked_up["item"]["quantity"], 1)
        _, after_scan, _ = self.request(f"/api/items/{item_id}")
        self.assertEqual(after_scan["item"]["quantity"], 1)

        status, listed, _ = self.request("/api/items?search=Kicher")
        self.assertEqual(status, 200)
        self.assertEqual(len(listed["items"]), 1)

        status, updated, _ = self.request(
            f"/api/items/{item_id}", "PATCH", {"quantity": 4}
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["item"]["quantity"], 4)

        status, deleted, _ = self.request(f"/api/items/{item_id}", "DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])

    def test_health_and_frontend_are_served(self) -> None:
        status, health, _ = self.request("/api/health")
        self.assertEqual((status, health["status"]), (200, "ok"))
        with urlopen(self.base_url + "/", timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["Content-Type"])
            self.assertIn(b"Lager", response.read())

    def test_validation_error_is_json(self) -> None:
        status, body, _ = self.request("/api/items", "POST", {"name": "  "})
        self.assertEqual(status, 400)
        self.assertEqual(body["field"], "name")

    def test_ingress_mode_rejects_direct_lan_requests(self) -> None:
        handler = self.server.RequestHandlerClass
        handler.require_ingress_proxy = True
        try:
            status, body, _ = self.request("/api/health")
        finally:
            handler.require_ingress_proxy = False
        self.assertEqual(status, 403)
        self.assertIn("Ingress", body["error"])


if __name__ == "__main__":
    unittest.main()
