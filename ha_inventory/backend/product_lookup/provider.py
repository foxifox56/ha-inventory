"""Safe, bounded read-only access to the Open Facts barcode API."""

from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_HOSTS = frozenset(
    {
        "world.openfoodfacts.org",
        "world.openbeautyfacts.org",
        "world.openpetfoodfacts.org",
        "world.openproductsfacts.org",
    }
)
FACTS_DOMAINS = {
    "food": ("Open Food Facts", "openfoodfacts.org"),
    "beauty": ("Open Beauty Facts", "openbeautyfacts.org"),
    "petfood": ("Open Pet Food Facts", "openpetfoodfacts.org"),
    "product": ("Open Products Facts", "openproductsfacts.org"),
}
IMAGE_HOST_SUFFIXES = tuple(
    facts_domain for _, facts_domain in FACTS_DOMAINS.values()
)
MAX_RESPONSE_BYTES = 512_000
MAX_REDIRECTS = 4
DEFAULT_TIMEOUT_SECONDS = 5
DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60
NOT_FOUND_CACHE_TTL_SECONDS = 5 * 60
DEFAULT_CACHE_SIZE = 256
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 4.1
BARCODE_PATTERN = re.compile(r"^[0-9]{1,64}$", re.ASCII)


class ProductLookupError(Exception):
    """A provider could not safely return a product lookup result."""


class ProductLookupUnavailable(ProductLookupError):
    """The remote service failed, timed out, or returned invalid data."""


class ProductLookupRateLimited(ProductLookupUnavailable):
    """A local request throttle or the provider rejected a request."""

    def __init__(
        self,
        message: str,
        retry_after_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
    ):
        super().__init__(message)
        delay = float(retry_after_seconds)
        self.retry_after_seconds = max(0.05, delay) if math.isfinite(delay) else DEFAULT_MIN_REQUEST_INTERVAL_SECONDS


@dataclass(frozen=True)
class ProductCandidate:
    barcode: str
    name: str
    brand: str
    product_size: str
    category: str
    image_url: str
    image_license: str
    data_source: str
    source_url: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _validate_api_url(url: str) -> None:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        raise ProductLookupUnavailable("Open-Facts-Weiterleitung wurde blockiert.") from None
    if (
        parsed.scheme != "https"
        or hostname not in API_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise ProductLookupUnavailable("Open-Facts-Weiterleitung wurde blockiert.")


class SafeOpenFactsRedirectHandler(HTTPRedirectHandler):
    """Follow only HTTPS redirects among the documented Open Facts API hosts."""

    max_redirections = MAX_REDIRECTS
    max_repeats = MAX_REDIRECTS

    def redirect_request(self, request, fp, code, message, headers, newurl):
        _validate_api_url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def _clean_text(value: Any, limit: int = 240) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = " ".join("".join(ch for ch in value if ch >= " " and ch != "\x7f").split())
    return cleaned[:limit]


def _image_url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        return ""
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        return ""
    allowed = any(
        hostname == domain or hostname.endswith("." + domain)
        for domain in IMAGE_HOST_SUFFIXES
    )
    if (
        parsed.scheme != "https"
        or not allowed
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        return ""
    return value


def _selected_front_image(product: dict[str, Any]) -> str:
    legacy_url = _image_url(product.get("image_front_url"))
    if legacy_url:
        return legacy_url

    def find_url(value: Any) -> str:
        if isinstance(value, dict):
            direct_url = _image_url(value.get("url"))
            if direct_url:
                return direct_url
            sizes = value.get("sizes")
            if isinstance(sizes, dict):
                for size in ("200", "400", "100", "full"):
                    found = find_url(sizes.get(size))
                    if found:
                        return found
            for child in value.values():
                found = find_url(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = find_url(child)
                if found:
                    return found
        return ""

    def find_front(value: Any) -> str:
        if isinstance(value, dict):
            for key, child in value.items():
                if "front" in str(key).lower():
                    found = find_url(child)
                    if found:
                        return found
            for child in value.values():
                found = find_front(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = find_front(child)
                if found:
                    return found
        return ""

    for field in ("selected_images", "images"):
        found = find_front(product.get(field))
        if found:
            return found
    return ""


def _category(product_type: Any, raw_categories: Any) -> str:
    kind = (
        product_type
        if isinstance(product_type, str) and product_type in FACTS_DOMAINS
        else "product"
    )
    default = {
        "food": "Lebensmittel",
        "beauty": "Kosmetik",
        "petfood": "Tierbedarf",
        "product": "Sonstiges",
    }[kind]
    if isinstance(raw_categories, str):
        categories = [part.strip() for part in raw_categories.split(",") if part.strip()]
        if categories:
            last = categories[-1]
            if last.startswith("en:"):
                last = last[3:].replace("-", " ")
            return _clean_text(last, 80) or default
    return default


class OpenFactsProvider:
    """The Open-Facts ecosystem provider using its universal product_type=all API."""

    name = "open-facts"

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        cache_size: int = DEFAULT_CACHE_SIZE,
        cache_ttl: float = DEFAULT_CACHE_TTL_SECONDS,
        not_found_ttl: float = NOT_FOUND_CACHE_TTL_SECONDS,
        min_request_interval: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
        opener=None,
        clock=time.monotonic,
    ):
        self.timeout = timeout
        self.cache_size = max(1, cache_size)
        self.cache_ttl = cache_ttl
        self.not_found_ttl = not_found_ttl
        self.min_request_interval = max(0, min_request_interval)
        self._clock = clock
        self._opener = opener or build_opener(SafeOpenFactsRedirectHandler())
        self._cache: OrderedDict[str, tuple[float, ProductCandidate | None]] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._last_request_at: float | None = None

    def lookup(self, barcode: str) -> ProductCandidate | None:
        if not isinstance(barcode, str) or not BARCODE_PATTERN.fullmatch(barcode):
            raise ValueError("Barcode muss aus 1 bis 64 Ziffern bestehen.")
        cached = self._cache_get(barcode)
        if cached is not _CACHE_MISS:
            return cached

        now = self._clock()
        with self._request_lock:
            now = self._clock()
            remaining = (
                self.min_request_interval - (now - self._last_request_at)
                if self._last_request_at is not None
                else 0
            )
            if remaining > 0:
                raise ProductLookupRateLimited(
                    "Open Facts begrenzt Anfragen kurz hintereinander.",
                    retry_after_seconds=remaining,
                )
            self._last_request_at = now

        candidate = self._request_product(barcode)
        self._cache_put(barcode, candidate)
        return candidate

    def _request_product(self, barcode: str) -> ProductCandidate | None:
        # Keep the string intact: an EAN/UPC beginning with zero must not be cast
        # to an integer, even though the upstream API may normalize GTIN variants.
        url = (
            "https://world.openfoodfacts.org/api/v3/product/"
            f"{quote(barcode, safe='')}.json?product_type=all&fields="
            "code,product_name,product_name_de,brands,quantity,"
            "categories,product_type,images,selected_images"
            "&generate_images_urls=true"
        )
        _validate_api_url(url)
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "HA-Inventory/0.2 (https://github.com/foxifox56/ha-inventory)",
            },
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                final_url = response.geturl()
                _validate_api_url(final_url)
                content_type = response.headers.get("Content-Type", "")
                if content_type and "json" not in content_type.lower():
                    raise ProductLookupUnavailable("Open Facts lieferte keine JSON-Antwort.")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ProductLookupUnavailable("Open-Facts-Antwort überschreitet das Größenlimit.")
        except HTTPError as error:
            if error.code == 404:
                return None
            if error.code == 429:
                retry_after = self.min_request_interval
                header = error.headers.get("Retry-After") if error.headers else None
                try:
                    if header is not None:
                        parsed_retry_after = float(header)
                        if math.isfinite(parsed_retry_after):
                            retry_after = max(0.05, parsed_retry_after)
                except (TypeError, ValueError):
                    pass
                raise ProductLookupRateLimited(
                    "Open Facts begrenzt Anfragen momentan.",
                    retry_after_seconds=retry_after,
                ) from error
            if error.code == 503:
                raise ProductLookupUnavailable("Open Facts ist momentan ausgelastet.") from error
            raise ProductLookupUnavailable(
                f"Open Facts antwortet mit HTTP {error.code}."
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ProductLookupUnavailable("Open Facts ist nicht erreichbar oder antwortet zu langsam.") from error

        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProductLookupUnavailable("Open Facts lieferte ungültiges JSON.") from error
        if not isinstance(body, dict):
            raise ProductLookupUnavailable("Open Facts lieferte ein ungültiges Antwortformat.")
        status = body.get("status")
        if (type(status) is int and status == 0) or status == "0":
            return None
        valid_status = (
            (type(status) is int and status == 1)
            or status == "1"
            or (
                isinstance(status, str)
                and status in {"success", "success_with_warnings", "success_with_errors"}
            )
        )
        if not valid_status or not isinstance(body.get("product"), dict):
            raise ProductLookupUnavailable("Open Facts lieferte ein unvollständiges Antwortformat.")

        product = body["product"]
        response_code = product.get("code")
        if response_code is not None:
            if (
                not isinstance(response_code, str)
                or not BARCODE_PATTERN.fullmatch(response_code)
                or response_code.lstrip("0") != barcode.lstrip("0")
            ):
                raise ProductLookupUnavailable("Open Facts antwortete mit einem abweichenden Barcode.")
        product_type = product.get("product_type")
        if not isinstance(product_type, str) or product_type not in FACTS_DOMAINS:
            product_type = "food"
        source_name, source_domain = FACTS_DOMAINS[product_type]
        product_page = f"https://world.{source_domain}/product/{quote(barcode, safe='')}"
        name = _clean_text(product.get("product_name_de")) or _clean_text(
            product.get("product_name")
        )
        image_url = _selected_front_image(product)
        return ProductCandidate(
            barcode=barcode,
            name=name,
            brand=_clean_text(product.get("brands"), 120),
            product_size=_clean_text(product.get("quantity"), 80),
            category=_category(product_type, product.get("categories")),
            image_url=image_url,
            image_license="CC BY-SA" if image_url else "",
            data_source=source_name,
            source_url=product_page,
        )

    def _cache_get(self, barcode: str):
        now = self._clock()
        with self._cache_lock:
            entry = self._cache.get(barcode)
            if entry is None:
                return _CACHE_MISS
            expires_at, candidate = entry
            if expires_at <= now:
                del self._cache[barcode]
                return _CACHE_MISS
            self._cache.move_to_end(barcode)
            return candidate

    def _cache_put(self, barcode: str, candidate: ProductCandidate | None) -> None:
        ttl = self.cache_ttl if candidate is not None else self.not_found_ttl
        with self._cache_lock:
            self._cache[barcode] = (self._clock() + ttl, candidate)
            self._cache.move_to_end(barcode)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)


_CACHE_MISS = object()
