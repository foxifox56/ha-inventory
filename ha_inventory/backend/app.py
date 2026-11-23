"""Application wiring for persistence, domain services, and HTTP."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Type

from .database import Database
from .inventory.repository import InventoryRepository
from .inventory.service import InventoryService
from .product_lookup import OpenFactsProvider, ProductLookupService
from .web.handler import InventoryRequestHandler


def create_handler(
    data_dir: Path,
    *,
    ingress_ip_check: bool = True,
    product_providers=None,
) -> Type[InventoryRequestHandler]:
    database = Database(Path(data_dir))
    database.initialize()
    service = InventoryService(InventoryRepository(database))
    providers = [OpenFactsProvider()] if product_providers is None else product_providers
    product_lookup = ProductLookupService(service, providers)

    class ConfiguredInventoryHandler(InventoryRequestHandler):
        inventory = service
        require_ingress_proxy = ingress_ip_check
        write_tokens: dict[str, float] = {}
        write_tokens_lock = threading.Lock()

    ConfiguredInventoryHandler.product_lookup = product_lookup
    return ConfiguredInventoryHandler
