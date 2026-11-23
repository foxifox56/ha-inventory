"""Threaded HTTP server for the app API and static frontend."""

from __future__ import annotations

from http.server import ThreadingHTTPServer
from typing import Type

from .handler import InventoryRequestHandler


class InventoryHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(handler: Type[InventoryRequestHandler], *, host: str, port: int) -> None:
    server = InventoryHTTPServer((host, port), handler)
    print(f"HA Inventory listening on {host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
