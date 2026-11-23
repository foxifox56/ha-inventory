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
    MAX_ITEM_CODE_LENGTH = 64

    def __init__(self, inventory: InventoryService, providers: list[ProductProvider]):
        self.inventory = inventory
        self.providers = tuple(providers)

    def lookup(self, barcode: str) -> dict[str, Any]:
        if not isinstance(barcode, str):
            raise InventoryError("Artikelcode muss Text mit 1 bis 64 Zeichen sein.", field="barcode")
        # Match InventoryService's barcode normalization. Item codes are stored
        # as text and may be numeric, alphanumeric, or contain punctuation.
        barcode = barcode.strip()
        if not barcode or len(barcode) > self.MAX_ITEM_CODE_LENGTH:
            raise InventoryError("Artikelcode muss 1 bis 64 Zeichen lang sein.", field="barcode")

        try:
            item = self.inventory.get_by_barcode(barcode)
        except InventoryError as error:
            if error.status_code != 404:
                raise
        else:
            return {"status": "local", "barcode": barcode, "item": item}

        # Open Facts only understands numeric product identifiers. An unknown
        # local code must still reach the manual form without a provider error.
        if not self.BARCODE_PATTERN.fullmatch(barcode):
            return {"status": "not_found", "barcode": barcode}

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
