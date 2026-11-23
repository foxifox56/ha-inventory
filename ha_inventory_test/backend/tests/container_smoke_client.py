"""Small stdlib-only HTTP client used by the isolated Docker smoke test."""

from __future__ import annotations

import json
import io
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from PIL import Image, ImageDraw, ImageFont


def request(
    base_url: str,
    path: str,
    method: str = "GET",
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 3,
):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.status, response.read(), response.headers
    except HTTPError as error:
        return error.code, error.read(), error.headers


def post_bytes(base_url: str, path: str, body: bytes, content_type: str, headers: dict[str, str], timeout: float = 30):
    req = Request(
        f"{base_url}{path}", data=body, method="POST",
        headers={"Content-Type": content_type, **headers},
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.status, response.read(), response.headers
    except HTTPError as error:
        return error.code, error.read(), error.headers


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: container_smoke_client COMMAND BASE_URL")
    command, base_url = sys.argv[1:]

    if command == "wait":
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                status, body, _ = request(base_url, "/api/v1/health")
                if status == 200 and json.loads(body)["status"] == "ok":
                    return
            except (URLError, TimeoutError, json.JSONDecodeError):
                pass
            time.sleep(0.5)
        raise SystemExit("Container did not become healthy within 30 seconds")

    if command == "frontend":
        status, body, headers = request(base_url, "/")
        assert status == 200, f"Unexpected frontend HTTP status: {status}"
        assert "text/html" in headers.get("Content-Type", "")
        assert b"detail-dialog" in body
        assert b"Verbrauchen" in body and b"history-dialog" in body
        assert b"Kassenbon" in body and b"receipt-ocr-languages" in body
        return

    if command == "receipt-ocr":
        languages = subprocess.run(
            ["tesseract", "--list-langs"], capture_output=True, text=True,
            timeout=10, check=True,
        ).stdout.splitlines()[1:]
        assert "deu" in languages and "eng" in languages, f"Required Tesseract languages missing: {languages!r}"
        image = Image.new("RGB", (1200, 500), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=42)
        for y, line in zip((35, 150, 265, 380), (
            "REWE", "2 X MILCH 1,09 2,18", "BANANEN 1,29", "SUMME 3,47",
        )):
            draw.text((50, y), line, font=font, fill="black")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")

        status, body, _ = request(base_url, "/api/v1/write-session")
        assert status == 200, f"Unable to get write session: HTTP {status}: {body!r}"
        token = json.loads(body)["write_token"]
        status, response, _ = post_bytes(
            base_url, "/api/v1/receipts/recognize", buffer.getvalue(), "image/png",
            {"X-HA-Inventory-Write-Token": token},
        )
        assert status == 200, f"Local receipt OCR failed: HTTP {status}: {response!r}"
        result = json.loads(response)
        assert result["merchant"] == "rewe", f"Merchant recognition failed: {result!r}"
        milk = next((line for line in result["lines"] if "MILCH" in line["label"].upper()), None)
        assert milk is not None, f"Tesseract did not read the receipt item: {result!r}"
        assert milk["quantity"] == 2, f"Explicit multiplier was not recognized: {milk!r}"
        assert result["ocr"]["languages"] == ["deu", "eng"]
        status, inventory, _ = request(base_url, "/api/v1/items")
        assert status == 200 and json.loads(inventory)["items"] == [], "OCR recognition must not create or change stock"
        return

    if command == "create":
        status, session_body, _ = request(base_url, "/api/v1/write-session")
        assert status == 200, f"Unable to get write session: HTTP {status}: {session_body!r}"
        token = json.loads(session_body)["write_token"]
        status, body, _ = request(
            base_url,
            "/api/v1/items",
            "POST",
            {
                "name": "Container smoke item",
                "barcode": "CI-SMOKE-001",
                "tracking_mode": "exact",
                "quantity": 5,
                "stock_status": "known",
            },
            {"X-HA-Inventory-Write-Token": token},
        )
        assert status == 201, f"Unexpected create HTTP status: {status}: {body!r}"
        item_id = json.loads(body)["item"]["id"]
        movement_payload = {
            "action": "consume", "quantity": 1,
            "source": "container-smoke", "idempotency_key": "container-smoke-consume-1",
        }
        status, movement_body, _ = request(
            base_url, f"/api/v1/items/{item_id}/movements", "POST", movement_payload,
            {"X-HA-Inventory-Write-Token": token},
        )
        assert status == 201, f"Unexpected movement HTTP status: {status}: {movement_body!r}"
        movement_id = json.loads(movement_body)["movement"]["id"]
        status, replay_body, _ = request(
            base_url, f"/api/v1/items/{item_id}/movements", "POST", movement_payload,
            {"X-HA-Inventory-Write-Token": token},
        )
        assert status == 200, f"Expected idempotent replay, got HTTP {status}: {replay_body!r}"
        status, undo_body, _ = request(
            base_url, f"/api/v1/movements/{movement_id}/undo", "POST",
            {"idempotency_key": "container-smoke-undo-1", "source": "container-smoke"},
            {"X-HA-Inventory-Write-Token": token},
        )
        assert status == 201, f"Unexpected undo HTTP status: {status}: {undo_body!r}"
        return

    if command == "read":
        status, body, _ = request(
            base_url, f"/api/v1/items/by-barcode/{quote('CI-SMOKE-001')}"
        )
        assert status == 200, f"Unexpected lookup HTTP status: {status}: {body!r}"
        item = json.loads(body)["item"]
        assert item["name"] == "Container smoke item"
        assert item["quantity"] == 5
        assert item["stock_status"] == "known"
        status, history_body, _ = request(base_url, f"/api/v1/items/{item['id']}/movements")
        assert status == 200, f"Unexpected movement history HTTP status: {status}"
        history = json.loads(history_body)["movements"]
        assert len(history) == 2, f"Movement history did not survive restart: {history!r}"
        original = next(entry for entry in history if entry["action"] == "consume")
        assert original["undone_by_movement_id"] is not None
        return

    if command == "denied":
        status, body, _ = request(base_url, "/api/v1/health")
        assert status == 403, f"Expected ingress rejection, got HTTP {status}"
        assert "Ingress" in json.loads(body)["error"]
        return

    raise SystemExit(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
