"""Local-first orchestration for optional external product providers."""

from __future__ import annotations

import re
from typing import Any, Protocol

from ..errors import InventoryError
from ..inventory.service import InventoryService
from .provider import ProductCandidate, ProductLookupError


class ProductProvider(Protocol):
    name: str

    def lookup(self, barcode: str) -> ProductCandidate | None: ...


class ProductLookupService:
    """Consult inventory first, then optional providers without persisting results."""

    BARCODE_PATTERN = re.compile(r"^[0-9]{1,64}$", re.ASCII)

    def __init__(self, inventory: InventoryService, providers: list[ProductProvider]):
        self.inventory = inventory
        self.providers = tuple(providers)

    def lookup(self, barcode: str) -> dict[str, Any]:
        if not isinstance(barcode, str) or not self.BARCODE_PATTERN.fullmatch(barcode):
            raise InventoryError("Barcode muss aus 1 bis 64 Ziffern bestehen.", field="barcode")

        try:
            item = self.inventory.get_by_barcode(barcode)
        except InventoryError as error:
            if error.status_code != 404:
                raise
        else:
            return {"status": "local", "barcode": barcode, "item": item}

        failures: list[ProductLookupError] = []
        for provider in self.providers:
            try:
                candidate = provider.lookup(barcode)
            except ProductLookupError as error:
                failures.append(error)
                continue
            if candidate is not None:
                return {
                    "status": "identified",
                    "barcode": barcode,
                    "product": candidate.as_dict(),
                }
        if failures:
            raise failures[-1]
        return {"status": "not_found", "barcode": barcode}
