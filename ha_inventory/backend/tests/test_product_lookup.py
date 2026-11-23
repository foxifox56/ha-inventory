from __future__ import annotations

import json
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request

from backend.database import Database
from backend.inventory.repository import InventoryRepository
from backend.inventory.service import InventoryService
from backend.product_lookup.provider import (
    OpenFactsProvider,
    ProductCandidate,
    ProductLookupRateLimited,
    ProductLookupUnavailable,
    SafeOpenFactsRedirectHandler,
    _validate_api_url,
)
from backend.product_lookup.service import ProductLookupService


class FakeResponse:
    def __init__(self, body, *, content_type="application/json", final_url=None):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.final_url = final_url or "https://world.openfoodfacts.org/api/v3/product/0001.json"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return self.final_url

    def read(self, limit=-1):
        return self.body if limit < 0 else self.body[:limit]


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return self.response


class ProductLookupProviderTests(unittest.TestCase):
    def provider(self, body, **kwargs):
        opener = kwargs.pop("opener", FakeOpener(FakeResponse(body)))
        return OpenFactsProvider(opener=opener, min_request_interval=0, **kwargs), opener

    def test_uses_universal_barcode_endpoint_and_preserves_leading_zeroes(self):
        body = {
            "status": "success_with_warnings",
            "product": {
                "code": "00012345",
                "product_type": "food",
                "product_name_de": "Haferdrink",
                "product_name": "Oat drink",
                "brands": "Beispiel",
                "quantity": "1 l",
                "categories": "Drinks, Plant-based drinks",
                "images": {
                    "selected": {
                        "front": {
                            "de": {"sizes": {"200": {
                                "url": "https://images.openfoodfacts.org/images/products/000/123/45/front.jpg"
                            }}}
                        }
                    }
                },
            },
        }
        provider, opener = self.provider(body)
        candidate = provider.lookup("00012345")
        request, timeout = opener.requests[0]
        self.assertTrue(request.full_url.startswith(
            "https://world.openfoodfacts.org/api/v3/product/00012345.json?product_type=all"
        ))
        self.assertIn("generate_images_urls=true", request.full_url)
        self.assertIn("HA-Inventory/0.2", request.get_header("User-agent"))
        self.assertEqual(timeout, 5)
        self.assertEqual(candidate.barcode, "00012345")
        self.assertEqual(candidate.name, "Haferdrink")
        self.assertEqual(candidate.brand, "Beispiel")
        self.assertEqual(candidate.product_size, "1 l")
        self.assertEqual(candidate.category, "Plant-based drinks")
        self.assertEqual(candidate.image_license, "CC BY-SA")
        self.assertEqual(candidate.data_source, "Open Food Facts")

    def test_supports_each_open_facts_product_type(self):
        types = {
            "food": ("Open Food Facts", "Lebensmittel"),
            "beauty": ("Open Beauty Facts", "Kosmetik"),
            "petfood": ("Open Pet Food Facts", "Tierbedarf"),
            "product": ("Open Products Facts", "Sonstiges"),
        }
        for product_type, (source, category) in types.items():
            with self.subTest(product_type=product_type):
                provider, _ = self.provider({
                    "status": "success", "product": {"product_type": product_type, "product_name": "Test"}
                })
                candidate = provider.lookup("00123")
                self.assertEqual(candidate.data_source, source)
                self.assertEqual(candidate.category, category)
                self.assertIn(product_type, candidate.source_url)

    def test_missing_product_metadata_and_untrusted_image_are_omitted_cleanly(self):
        provider, _ = self.provider({
            "status": "success",
            "product": {
                "product_type": "petfood",
                "image_front_url": "https://attacker.example/picture.jpg",
            },
        })
        candidate = provider.lookup("0009")
        self.assertEqual(candidate.name, "")
        self.assertEqual(candidate.brand, "")
        self.assertEqual(candidate.product_size, "")
        self.assertEqual(candidate.category, "Tierbedarf")
        self.assertEqual(candidate.image_url, "")

    def test_provider_returns_not_found_for_status_zero_and_caches_it(self):
        provider, opener = self.provider({"status": 0, "product": None})
        self.assertIsNone(provider.lookup("0008"))
        self.assertIsNone(provider.lookup("0008"))
        self.assertEqual(len(opener.requests), 1)

    def test_cache_has_a_size_limit_and_expires_not_found_entries(self):
        now = [0.0]
        opener = FakeOpener(FakeResponse({"status": 0, "product": None}))
        provider = OpenFactsProvider(
            opener=opener, clock=lambda: now[0], min_request_interval=0,
            cache_size=1, not_found_ttl=2,
        )
        self.assertIsNone(provider.lookup("0001"))
        self.assertIsNone(provider.lookup("0002"))
        self.assertLessEqual(len(provider._cache), 1)
        self.assertIsNone(provider.lookup("0001"))  # evicted by the second key
        now[0] = 5.0
        self.assertIsNone(provider.lookup("0001"))  # expired negative result
        self.assertEqual(len(opener.requests), 4)

    def test_network_timeout_invalid_json_and_invalid_response_fail_cleanly(self):
        timeout_provider, _ = self.provider(
            {}, opener=FakeOpener(error=URLError(TimeoutError("socket timeout")))
        )
        with self.assertRaises(ProductLookupUnavailable):
            timeout_provider.lookup("0011")

        invalid_json, _ = self.provider(b"not json")
        with self.assertRaises(ProductLookupUnavailable):
            invalid_json.lookup("0012")

        invalid_schema, _ = self.provider({"status": "success", "product": []})
        with self.assertRaises(ProductLookupUnavailable):
            invalid_schema.lookup("0013")

        wrong_barcode, _ = self.provider({
            "status": "success", "product": {"code": "9999", "product_name": "Falscher Artikel"}
        })
        with self.assertRaises(ProductLookupUnavailable):
            wrong_barcode.lookup("0013")

        invalid_status, _ = self.provider({"status": True, "product": {}})
        with self.assertRaises(ProductLookupUnavailable):
            invalid_status.lookup("0013")

        wrong_type, _ = self.provider(
            {"status": "success", "product": {}},
            opener=FakeOpener(FakeResponse({}, content_type="text/html")),
        )
        with self.assertRaises(ProductLookupUnavailable):
            wrong_type.lookup("0014")

    def test_rate_limits_are_not_retried_and_http_503_is_clean(self):
        provider = OpenFactsProvider(
            opener=FakeOpener(FakeResponse({"status": 0})), min_request_interval=4.1, clock=lambda: 10.0
        )
        self.assertIsNone(provider.lookup("0015"))
        with self.assertRaises(ProductLookupRateLimited):
            provider.lookup("0016")

        overloaded = OpenFactsProvider(
            opener=FakeOpener(error=HTTPError("https://world.openfoodfacts.org", 503, "busy", {}, None)),
            min_request_interval=0,
        )
        with self.assertRaises(ProductLookupRateLimited):
            overloaded.lookup("0017")

    def test_redirect_urls_are_limited_to_https_open_facts_api_hosts(self):
        _validate_api_url("https://world.openbeautyfacts.org/api/v3/product/001.json")
        with self.assertRaises(ProductLookupUnavailable):
            _validate_api_url("http://world.openfoodfacts.org/api/v3/product/001.json")
        with self.assertRaises(ProductLookupUnavailable):
            _validate_api_url("https://world.openfoodfacts.org.evil.example/api/v3/product/001.json")
        with self.assertRaises(ProductLookupUnavailable):
            _validate_api_url("https://world.openfoodfacts.org:444/api/v3/product/001.json")

        handler = SafeOpenFactsRedirectHandler()
        request = Request("https://world.openfoodfacts.org/api/v3/product/001.json")
        redirected = handler.redirect_request(
            request, None, 302, "Found", {},
            "https://world.openproductsfacts.org/api/v3/product/001.json",
        )
        self.assertEqual(redirected.full_url, "https://world.openproductsfacts.org/api/v3/product/001.json")
        with self.assertRaises(ProductLookupUnavailable):
            handler.redirect_request(
                request, None, 302, "Found", {}, "https://evil.example/redirect"
            )

    def test_provider_chain_can_add_a_future_specialist_data_source(self):
        class EmptyOpenFacts:
            name = "open-facts"

            def lookup(self, _barcode):
                return None

        class ToolsCatalog:
            name = "tools-catalog"

            def lookup(self, barcode):
                return ProductCandidate(
                    barcode=barcode, name="Akkuschrauber", brand="Werkzeug GmbH",
                    product_size="18 V", category="Werkzeuge", image_url="",
                    image_license="",
                    data_source="Tools Catalog", source_url="https://catalog.example/item",
                )

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory))
            database.initialize()
            inventory = InventoryService(InventoryRepository(database))
            result = ProductLookupService(inventory, [EmptyOpenFacts(), ToolsCatalog()]).lookup("00052")
        self.assertEqual(result["status"], "identified")
        self.assertEqual(result["product"]["data_source"], "Tools Catalog")
        self.assertEqual(result["product"]["barcode"], "00052")


if __name__ == "__main__":
    unittest.main()
