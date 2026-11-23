"""HTTP routing, request validation, and static frontend delivery."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from ..errors import InventoryError
from ..inventory.service import InventoryService


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
MAX_REQUEST_BYTES = 1_000_000
INGRESS_PROXY_IP = "172.30.32.2"


def ingress_request_allowed(client_ip: str, required: bool = True) -> bool:
    return not required or client_ip == INGRESS_PROXY_IP


class InventoryRequestHandler(BaseHTTPRequestHandler):
    inventory: InventoryService
    require_ingress_proxy = True
    server_version = "HAInventory/0.1"

    def do_GET(self) -> None:
        if not self._allow_request():
            return
        parsed = urlsplit(self.path)
        if parsed.path.startswith("/api/"):
            self._get_api(parsed.path, parse_qs(parsed.query))
        else:
            self._serve_static(parsed.path)

    def do_POST(self) -> None:
        if not self._allow_request():
            return
        parsed = urlsplit(self.path)
        if parsed.path != "/api/items":
            self._json_response(404, {"error": "Route nicht gefunden."})
            return
        try:
            item = self.inventory.create(self._read_json())
            self._json_response(201, {"item": item})
        except InventoryError as error:
            self._inventory_error(error)

    def do_PATCH(self) -> None:
        if not self._allow_request():
            return
        item_id = self._item_id(urlsplit(self.path).path)
        if item_id is None:
            self._json_response(404, {"error": "Route nicht gefunden."})
            return
        try:
            item = self.inventory.update(item_id, self._read_json())
            self._json_response(200, {"item": item})
        except InventoryError as error:
            self._inventory_error(error)

    def do_DELETE(self) -> None:
        if not self._allow_request():
            return
        item_id = self._item_id(urlsplit(self.path).path)
        if item_id is None:
            self._json_response(404, {"error": "Route nicht gefunden."})
            return
        try:
            self.inventory.delete(item_id)
            self._json_response(200, {"deleted": True})
        except InventoryError as error:
            self._inventory_error(error)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)

    def _allow_request(self) -> bool:
        if ingress_request_allowed(self.client_address[0], self.require_ingress_proxy):
            return True
        self._json_response(403, {"error": "Zugriff nur über Home Assistant Ingress."})
        return False

    def _get_api(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/health":
            self._json_response(200, {"status": "ok"})
            return
        if path == "/api/items":
            items = self.inventory.list_items(
                search=query.get("search", [""])[0],
                category=query.get("category", [""])[0],
            )
            self._json_response(200, {"items": items})
            return
        prefix = "/api/items/barcode/"
        if path.startswith(prefix):
            try:
                item = self.inventory.get_by_barcode(unquote(path[len(prefix) :]))
                self._json_response(200, {"item": item})
            except InventoryError as error:
                self._inventory_error(error)
            return
        item_id = self._item_id(path)
        if item_id is not None:
            try:
                self._json_response(200, {"item": self.inventory.get(item_id)})
            except InventoryError as error:
                self._inventory_error(error)
            return
        self._json_response(404, {"error": "Route nicht gefunden."})

    @staticmethod
    def _item_id(path: str) -> int | None:
        prefix = "/api/items/"
        if not path.startswith(prefix):
            return None
        item_id_text = path[len(prefix) :]
        if not item_id_text.isdecimal():
            return None
        item_id = int(item_id_text)
        return item_id if item_id > 0 else None

    def _read_json(self) -> dict[str, object]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            raise InventoryError("Ungültige Content-Length.") from None
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise InventoryError("Anfrage ist zu groß.", status_code=413)
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise InventoryError("Ungültiger JSON-Inhalt.") from None
        if not isinstance(body, dict):
            raise InventoryError("Die Anfrage muss ein JSON-Objekt enthalten.")
        return body

    def _inventory_error(self, error: InventoryError) -> None:
        body: dict[str, object] = {"error": error.message}
        if error.field:
            body["field"] = error.field
        self._json_response(error.status_code, body)

    def _json_response(self, status: int, body: dict[str, object]) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(encoded)

    def _serve_static(self, request_path: str) -> None:
        decoded = unquote(request_path)
        relative = "index.html" if decoded in {"", "/"} else decoded.lstrip("/")
        target = (FRONTEND_DIR / relative).resolve()
        if not target.is_relative_to(FRONTEND_DIR.resolve()) or not target.is_file():
            self._json_response(404, {"error": "Datei nicht gefunden."})
            return
        content = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {
            "application/javascript",
            "application/json",
        }:
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self._security_headers()
        self.end_headers()
        self.wfile.write(content)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'self'",
        )
