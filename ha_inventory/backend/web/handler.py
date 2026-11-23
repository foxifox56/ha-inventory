"""HTTP routing, request validation, and static frontend delivery."""

from __future__ import annotations

import json
import math
import mimetypes
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from ..errors import InventoryError
from ..inventory.service import InventoryService
from ..product_lookup.provider import ProductLookupError, ProductLookupRateLimited


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
MAX_REQUEST_BYTES = 1_000_000
INGRESS_PROXY_IP = "172.30.32.2"
WRITE_SESSION_TTL_SECONDS = 3600
API_VERSION = "1"
STOCK_STATUSES = (
    {"value": "unknown", "label": "Unbekannt"},
    {"value": "present", "label": "Vorhanden"},
    {"value": "out_of_stock", "label": "Nicht vorhanden"},
    {"value": "known", "label": "Menge erfasst"},
)


def ingress_request_allowed(client_ip: str, required: bool = True) -> bool:
    return not required or client_ip == INGRESS_PROXY_IP


class InventoryRequestHandler(BaseHTTPRequestHandler):
    inventory: InventoryService
    product_lookup: object
    require_ingress_proxy = True
    write_tokens: dict[str, float] = {}
    write_tokens_lock = threading.Lock()
    server_version = "HAInventory/0.2"

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
        path = urlsplit(self.path).path
        if path not in {"/api/items", "/api/v1/items"}:
            self._json_response(404, {"error": "Route nicht gefunden."})
            return
        if not self._allow_write():
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
        if not self._allow_write():
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
        if not self._allow_write():
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
        self._json_response(
            403,
            {"code": "ingress_required", "error": "Zugriff nur über Home Assistant Ingress."},
        )
        return False

    def _get_api(self, path: str, query: dict[str, list[str]]) -> None:
        api_root = "/api/v1/" if path.startswith("/api/v1/") else "/api/"
        api_path = "/" + path[len(api_root) :] if path.startswith(api_root) else path
        if api_path == "/health":
            self._json_response(200, {"status": "ok"})
            return
        if api_root == "/api/v1/" and api_path == "/write-session":
            self._issue_write_session()
            return
        product_lookup_prefix = "/product-lookup/"
        if api_root == "/api/v1/" and api_path.startswith(product_lookup_prefix):
            barcode = unquote(api_path[len(product_lookup_prefix) :])
            try:
                result = self.product_lookup.lookup(barcode)
                self._json_response(200, result)
            except InventoryError as error:
                self._inventory_error(error)
            except ProductLookupRateLimited as error:
                retry_after = error.retry_after_seconds
                self._json_response(
                    429,
                    {
                        "code": "product_lookup_rate_limited",
                        "status": "rate_limited",
                        "barcode": barcode,
                        "retry_after_seconds": retry_after,
                        "error": str(error),
                    },
                    extra_headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
                )
            except ProductLookupError as error:
                self._json_response(
                    503,
                    {"code": "product_lookup_unavailable", "status": "unavailable",
                     "barcode": barcode, "error": str(error)},
                )
            return
        if api_path == "/items":
            items = self.inventory.list_items(
                search=query.get("search", [""])[0],
                category=query.get("category", [""])[0],
                location=query.get("location", [""])[0],
                stock_status=query.get("stock_status", [""])[0],
            )
            self._json_response(200, {"items": items})
            return
        if api_root == "/api/v1/" and api_path == "/categories":
            items = self.inventory.list_items()
            categories = sorted({item["category"] for item in items}, key=str.casefold)
            self._json_response(200, {"categories": categories})
            return
        if api_root == "/api/v1/" and api_path == "/locations":
            items = self.inventory.list_items()
            locations = sorted(
                {item["location"].strip() for item in items if item["location"].strip()},
                key=str.casefold,
            )
            self._json_response(200, {"locations": locations})
            return
        if api_root == "/api/v1/" and api_path == "/stock-statuses":
            self._json_response(200, {"stock_statuses": list(STOCK_STATUSES)})
            return
        barcode_prefixes = [
            "/api/items/barcode/",
            "/api/v1/items/by-barcode/",
        ]
        barcode_prefix = next((prefix for prefix in barcode_prefixes if path.startswith(prefix)), None)
        if barcode_prefix:
            try:
                item = self.inventory.get_by_barcode(unquote(path[len(barcode_prefix) :]))
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
        prefixes = ("/api/items/", "/api/v1/items/")
        prefix = next((value for value in prefixes if path.startswith(value)), None)
        if prefix is None:
            return None
        item_id_text = path[len(prefix) :]
        if not item_id_text.isdecimal():
            return None
        item_id = int(item_id_text)
        return item_id if item_id > 0 else None

    def _issue_write_session(self) -> None:
        now = time.monotonic()
        token = secrets.token_urlsafe(32)
        with self.write_tokens_lock:
            for expired_token, expires_at in list(self.write_tokens.items()):
                if expires_at <= now:
                    del self.write_tokens[expired_token]
            if len(self.write_tokens) >= 500:
                oldest = min(self.write_tokens, key=self.write_tokens.get)
                del self.write_tokens[oldest]
            self.write_tokens[token] = now + WRITE_SESSION_TTL_SECONDS
        self._json_response(
            200,
            {"write_token": token, "expires_in": WRITE_SESSION_TTL_SECONDS},
        )

    def _allow_write(self) -> bool:
        token = self.headers.get("X-HA-Inventory-Write-Token", "")
        with self.write_tokens_lock:
            expires_at = self.write_tokens.get(token)
        if expires_at is not None and expires_at > time.monotonic():
            return True
        self._json_response(
            403,
            {
                "code": "write_session_invalid",
                "error": "Schreibzugriff benötigt eine gültige HA-Inventory-Schreibsitzung.",
            },
        )
        return False

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

    def _json_response(
        self,
        status: int,
        body: dict[str, object],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-HA-Inventory-API-Version", API_VERSION)
        self.send_header("Vary", "Origin")
        self._security_headers()
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
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
            "img-src 'self' data: https://openfoodfacts.org https://*.openfoodfacts.org "
            "https://openbeautyfacts.org https://*.openbeautyfacts.org "
            "https://openpetfoodfacts.org https://*.openpetfoodfacts.org "
            "https://openproductsfacts.org https://*.openproductsfacts.org; "
            "connect-src 'self'; media-src 'self' blob:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'self'",
        )
