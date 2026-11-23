"""External product lookup providers and orchestration."""

from .provider import OpenFactsProvider, ProductCandidate, ProductLookupError
from .service import ProductLookupService

__all__ = [
    "OpenFactsProvider",
    "ProductCandidate",
    "ProductLookupError",
    "ProductLookupService",
]
