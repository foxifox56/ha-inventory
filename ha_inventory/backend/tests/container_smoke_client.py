"""Small stdlib-only HTTP client used by the isolated Docker smoke test."""

from __future__ import annotations

import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def request(
    base_url: str,
    path: str,
    method: str = "GET",
    body: dict | None = None,
    headers: dict[str, str] | None = None,
):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urlopen(req, timeout=3) as response:
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
        return

    if command == "denied":
        status, body, _ = request(base_url, "/api/v1/health")
        assert status == 403, f"Expected ingress rejection, got HTTP {status}"
        assert "Ingress" in json.loads(body)["error"]
        return

    raise SystemExit(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
