"""Application wiring for persistence, domain services, and HTTP."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Type

from .database import Database
from .inventory.repository import InventoryRepository
from .inventory.service import InventoryService
from .web.handler import InventoryRequestHandler


def create_handler(
    data_dir: Path, *, ingress_ip_check: bool = True
) -> Type[InventoryRequestHandler]:
    database = Database(Path(data_dir))
    database.initialize()
    service = InventoryService(InventoryRepository(database))

    class ConfiguredInventoryHandler(InventoryRequestHandler):
        inventory = service
        require_ingress_proxy = ingress_ip_check
        write_tokens: dict[str, float] = {}
        write_tokens_lock = threading.Lock()

    return ConfiguredInventoryHandler
