# HA Inventory REST API

The canonical API for new clients is **`/api/v1`**. All requests must go through the Home Assistant Ingress URL. Home Assistant authenticates the user before forwarding the request, and the app accepts network traffic only from the Supervisor ingress proxy (`172.30.32.2`). The app exposes no host port and sends no CORS permission headers.

Responses include `X-HA-Inventory-API-Version: 1`. Item responses include a persistent SQLite `id` that is independent of the optional barcode. SQLite uses `INTEGER PRIMARY KEY AUTOINCREMENT`; schema migrations preserve existing IDs, and deleting an item does not make its ID available to a later item.

## Read endpoints

All responses are JSON with `Cache-Control: no-store`.

| Method and path | Response | Notes |
| --- | --- | --- |
| `GET /api/v1/health` | `{"status":"ok"}` | Health check, still behind Ingress. |
| `GET /api/v1/items` | `{"items":[...]}` | Optional `search`, `category`, `location`, and `stock_status` query parameters. |
| `GET /api/v1/items/{id}` | `{"item":{...}}` | Looks up the durable numeric item ID. |
| `GET /api/v1/items/by-barcode/{barcode}` | `{"item":{...}}` | Barcodes are strings; encode reserved URL characters and retain leading zeroes. This read never changes stock. |
| `GET /api/v1/categories` | `{"categories":["..."]}` | Current distinct category values. |
| `GET /api/v1/locations` | `{"locations":["..."]}` | Current non-empty distinct location values. |
| `GET /api/v1/stock-statuses` | `{"stock_statuses":[{"value":"...","label":"..."}]}` | Status vocabulary for `stock_status`. |
| `GET /api/v1/product-lookup/{barcode}` | One of the product lookup response objects below | Local-first, read-only lookup. Item codes are strings up to 64 characters; numeric codes retain leading zeroes. |

An item contains `id`, `name`, `barcode`, `brand`, `product_size`, `image_url`, `image_license`, `data_source`, `source_url`, `category`, `location`, `tracking_mode`, `stock_status`, `quantity`, `unit`, `minimum_quantity`, `notes`, `created_at`, and `updated_at`. `quantity` is `null` when the amount is unknown; it is never inferred from a barcode. `tracking_mode` is `simple`, `inventory`, or `exact`. Status is `unknown`, `present`, `out_of_stock`, or `known`.

### Product lookup response

The endpoint checks SQLite before making any remote request. An existing local item code, numeric or alphanumeric, returns `200 {"status":"local","barcode":"...","item":{...}}`. For an unknown numeric code, a recognized external product returns `200 {"status":"identified","barcode":"...","product":{...}}`; the suggestion includes `name`, `brand`, `product_size`, `category`, `image_url`, `image_license`, `data_source`, and `source_url`. An unknown alphanumeric code, or an external miss, returns `200 {"status":"not_found","barcode":"..."}` and does not contact Open Facts. Invalid or overlong codes return `400`.

An app-local Open Facts throttle or upstream HTTP 429 returns `429` with `code: "product_lookup_rate_limited"`, `status: "rate_limited"`, and `retry_after_seconds`; the response also includes the standard `Retry-After` header. The browser waits for at most two retries and no more than 12 seconds total, and that wait can be cancelled in favor of manual entry. Provider downtime, timeout, or invalid provider data returns `503 {"status":"unavailable", ...}`. Ingress access failures remain `403`. The backend does not wait in a queue or sleep for a future request slot.

This is a read-only endpoint. It never creates an item and never changes location, stock status, quantity, or any other database field. A client may prefill an editable form with `product`, but must wait for a user-confirmed `POST /api/v1/items` before persisting. The UI keeps its safe default stock state (`simple` / `unknown` / `null`); the user may choose a location and tracking mode before saving.

The current provider uses the Open Facts universal v3 barcode endpoint with `product_type=all` and accepts redirects only to the four documented HTTPS API hosts. It sends the barcode only, uses a five-second timeout and a product-specific User-Agent, caps the response at 512 KiB, and does not sleep or retry internally. An in-memory LRU cache holds up to 256 hits for six hours and misses for five minutes. Uncached requests are spaced by at least 4.1 seconds per app process to stay below Open Facts' documented 15 read requests/minute/IP limit. Early requests receive a bounded retry delay instead of occupying a backend worker; the browser shows the wait state and offers a manual fallback. The cache disappears at process restart. See [architecture.md](architecture.md) for provider extension, source attribution, image licensing, and known data-quality limitations.

## Write endpoints

Mutations require both the Ingress authenticated request and a short-lived write session:

1. Request `GET /api/v1/write-session` through the authenticated Ingress URL.
2. Send the returned `write_token` in `X-HA-Inventory-Write-Token` for each mutation. The token expires after one hour, stays in the app's memory, and is lost when the page reloads. It is not sent in a URL.

| Method and path | Response | Effect |
| --- | --- | --- |
| `POST /api/v1/items` | `201 {"item":{...}}` | Creates an item. |
| `PATCH /api/v1/items/{id}` | `200 {"item":{...}}` | Updates only submitted fields. Stock changes only when its fields are explicitly submitted. |
| `DELETE /api/v1/items/{id}` | `200 {"deleted":true}` | Deletes the selected item. |

The extra write session is a same-origin, cross-site-request protection layer on top of Home Assistant authentication. It does **not** create separate Home Assistant user roles or authorize clients outside Ingress. Do not treat it as an API key. An expired or invalid session returns `403` with `code: "write_session_invalid"`; the browser client refreshes and retries the mutation once. Other `403` responses (for example `code: "ingress_required"`) are surfaced without retry. Direct client access, cross-origin access, bearer-token authentication, or an integration bypassing Ingress are not implemented. These require a separately reviewed authentication design before enabling an external integration.

Errors return a JSON object such as `{"error":"...","field":"name"}` and an appropriate HTTP status. Duplicate barcodes return `409`; validation errors return `400`; missing items return `404`; writes without a valid session return `403`.

## Versioning and compatibility

Additive response fields and optional query filters may be added within v1. A breaking contract change requires a new path such as `/api/v2`; existing v1 callers must remain supported during that change.

The unversioned `/api` read routes from version 0.1 remain as a compatibility alias in 0.2. Mutations on those paths also require the new write-session header, so old write clients must move to v1. New clients must use `/api/v1`.
