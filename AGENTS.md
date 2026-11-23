# Development guide

## Architecture

- `ha_inventory/backend/inventory/` owns inventory rules and persistence. Keep HTTP concerns out of this package.
- `ha_inventory/backend/product_lookup/` owns provider protocols, remote product parsing, source attribution, cache and network safety. It must call the local inventory first through the product lookup service and never persist a result.
- `ha_inventory/backend/receipt/` owns image validation, local OCR adapter, receipt parser, local/learned product matching, privacy-safe fingerprints, atomic import, and bulk undo. The HTTP layer may enforce request size and content type, but receipt business rules and batch coordination stay here.
- `ha_inventory/backend/web/` adapts HTTP to the service and serves static files. The canonical API contract is versioned under `/api/v1`; document compatibility and breaking changes in `docs/API.md`.
- `ha_inventory/frontend/` is a browser-only API client. It must never read or write SQLite directly. Keep navigation, scanner lifecycle, and stock presentation in small focused modules.
- The REST API is independent of the UI. Other applications use its documented endpoints and durable item IDs, never the database file.
- `ha_inventory/backend/database.py` owns schema initialization and migrations. Persist app data only in the Home Assistant `/data` mount and preserve existing article IDs/data during migrations.
- A future Home Assistant integration belongs under `custom_components/ha_inventory/`; it must be an API client, not a second persistence layer. No integration may receive a browser-visible `SUPERVISOR_TOKEN`.
- Home Assistant packaging stays in `ha_inventory/config.yaml` and `ha_inventory/Dockerfile`. Do not require privileged mode, host networking, Home Assistant config-directory access, or an exposed host port.

## Product and security rules

- Home Assistant Ingress is the authentication boundary. Accept app requests only from the Supervisor proxy (`172.30.32.2`). Do not add external routes, CORS access, or ports that bypass Ingress.
- Reads remain read-only. Mutations require the additional short-lived write session as well as Ingress. The write session is not an external API credential or a replacement for Home Assistant authorization.
- A barcode identifies an inventory item but does not define its identity. Preserve the durable database ID if a barcode is changed or removed.
- Scan lookup must check SQLite first for any valid stored item code, numeric or alphanumeric. Only unknown numeric codes may go to Open Facts; unknown alphanumeric codes go directly to manual entry.
- The scanner opens in read-only `Ansehen` mode. Only a deliberate switch to `Verbrauchen` may book the selected unit count on a known numeric item; `Einlagern` always requires a separate confirmation.
- Product lookup results are suggestions only. An unknown barcode can prefill editable name, brand, pack size, category, and image fields, but only an explicit protected save may create an item. A lookup must never mutate stock.
- Receipt OCR is local-only: Tesseract runs inside the app container with bounded time, one image worker, and `deu`/`eng` data. Accept only bounded JPEG/PNG uploads; never add cloud OCR or persist source images/full OCR transcripts. The browser may locally decode HEIC, crop, rotate, resize, and convert to JPEG, but it must keep a recovery message when the browser cannot decode a photo.
- Receipt parsing is a user-reviewed suggestion. Merchant hints prioritize REWE and Kaufland, but parser output is never authoritative. Ignore known Pfand, return, discount, coupon, total, payment, and store lines; never parse a price as a count. Mark unpriced/uncertain quantities for review. A scan or OCR recognition alone must never create an article or mutate stock.
- Parse split receipt quantities only when a clear count/multiplier marker (`2 x ...`, `2 STK`) follows a product line. The preceding product may already include a price. A price is never itself a count; if discount/deposit/numeric continuation lines make the association ambiguous, retain the count only as a review-required suggestion. Keep an unknown quantity `null` in the API and blank in the form; never default it to one. Block the import until the user enters a valid whole quantity.
- Receipt photo/OCR work is generation-guarded. A new photo or explicit cancel invalidates the current recognition, aborts its HTTP request where possible, and prevents late processing/OCR results or errors from changing the UI/session state. After each async boundary, verify that the request still belongs to the selected photo. Lock photo controls during batch import/undo and keep receipt state stable until the transaction resolves.
- Receipt import requires explicit row decisions and one user confirmation. New articles, learned aliases, receipt status, and all stock movements must share a SQLite transaction. Route every stock update through `StockMovementService`; record `source=receipt`, receipt ID, and source line IDs. Use durable idempotency keys and recheck duplicate fingerprints inside the import transaction.
- Bulk receipt undo reverses every receipt stock movement inside one transaction or none. If any movement is unsafe after later activity, roll back the entire undo. It does not delete newly created articles or learned aliases: new articles remain with unknown stock and aliases remain mapped. The confirmation UI and docs must state this before the user undoes the booking; preserve audit history and durable IDs.
- External providers run only on the backend. Require HTTPS, a clear User-Agent, bounded timeouts/response bodies/cache, validated redirects and image/source URLs, and graceful provider failures. Respect provider rate limits without blocking a backend worker; expose retry guidance so the frontend can perform only bounded, cancellable waits and retain a manual fallback. Do not send locations, quantities, or other inventory data to a product provider. Keep provider-specific details out of the UI and SQLite layer.
- Preserve source attribution and image licensing when external metadata is saved or shown. Treat external data as unverified user-contributed suggestions.
- Stock changes use `StockMovementService`, a transaction, and a unique idempotency key. Never patch a quantity directly. Unknown/simple stock needs an explicit confirmed initialization; a confirmed zero is `known/0`, while receive and consume still require a positive whole count. Consumption may never make a quantity negative. Undo creates one audited counter-movement and cannot repeat; an initialization can only be undone when every later effective movement has itself been undone.
- Bound each movement quantity and resulting numeric stock at `Number.MAX_SAFE_INTEGER` (`9,007,199,254,740,991`) before SQLite binding, returning a validation error rather than allowing integer overflow or rounded browser values. An initialization replay is the same request only when quantity, tracking mode, and explicit confirmation all match; a reused key with a different mode must return `409`.
- Browser mutations retain the same idempotency key for an unresolved booking intent, including after an ambiguous network failure. A new key is created only after a confirmed response completes that intent. Undo requests follow the same rule. Mode changes invalidate and abort in-flight barcode lookups; the confirmed mode is checked again immediately before a scan mutation is sent, including after write-session refresh. Stale lookup responses must never route into a booking.
- Movement history is durable and keeps its item reference. Items with movement history are not physically deleted. Product pack size is metadata, not a quantity multiplier; booking counts are whole packages.
- Shopping/to-do completion and future HA events must never alter inventory silently.
- Represent presence-only, estimated inventory, and exact manual counts as distinct tracking modes. A missing count remains explicitly unknown, never zero or one.
- Keep product lookup and other remote integrations optional. The app must remain usable without a cloud database or cloud product account.
- Before enabling a future external client, define least-privilege authentication, revocation, and session handling. Never use direct SQLite access to avoid this work.

## Development guidelines

- Keep modules small and focused; add domain behavior to the service layer, not HTTP handlers or browser code.
- Use parameterized SQL, validate all API input, and escape user-provided values before rendering HTML.
- Preserve leading zeroes in barcodes and treat barcodes as strings.
- Add a database migration when changing the schema; do not edit existing migrations.
- Migrations must preserve legacy item IDs, barcodes, notes, locations, confirmed stock values, product metadata, movement IDs, idempotency keys, and undo references. Migration v5 adds the movement ledger; v6 rebuilds only that ledger to permit a zero initialization and its inverse; v7 adds receipt metadata, learned aliases, and optional movement links. All migrations preserve item rows and existing journal history.
- Use the Python standard library unless an additional dependency has a clear user-facing benefit. Vendor browser dependencies locally, pin the version, and include license notices.
- Keep the UI mobile-first, retain a usable desktop layout, provide manual barcode entry, honor reduced motion, and support system Dark Mode.
- A PWA manifest, service worker, standalone metadata, or alternate iPhone auth flow may only be added after `docs/PWA-architecture.md`'s security questions are resolved and documented.
- Keep shopping-list operations explicit and idempotent. Check for duplicates before writing, and never change inventory when a to-do item is completed.
- Add/update backend `unittest` and frontend Node test coverage for behavior changes, including zero baselines, unresolved network retries, and lookup mode races. From `ha_inventory/`, run:

  ```bash
  python3 -m unittest discover -s backend/tests -v
  node --test frontend/tests/*.test.mjs
  python3 -m pip install -r requirements.txt
  python3 -m compileall -q backend
  node --check frontend/app.js
  ```

- Product lookup tests must cover local-first behavior, all enabled provider types, missing fields/images, network/timeout/schema failures, leading-zero barcodes, cache/rate behavior, and proof that a lookup does not create or alter an item. Frontend tests must cover suggestions, manual fallback, loading, scanner mode routing, duplicate scan cooldown, booking quantity semantics, and undo affordances. Backend tests must cover idempotency, concurrent consumption, undo, movement history, negative stock protection, and migration v5/v6/v7.
- Receipt tests must cover REWE/Kaufland/generic detection, price-vs-quantity parsing, missing/uncertain lines, aliases, duplicate warnings and overrides, local image validation, no writes during recognition, atomic import and bulk undo, idempotent lost-response retries, and v6→v7 preservation. AMD64 and ARM64 container checks must use a synthetic receipt and the actual local Tesseract executable with both German and English data; do not label these as iPhone or Pi hardware tests.

- Update `README.md`, `TESTING.md`, `docs/API.md`, and architecture notes when setup, API behavior, security, or verification changes.
- Never install or configure this app on the user's production Home Assistant during development. Use local tests or an isolated test environment.
- Work on a development branch and leave integration into `main` for review. Do not configure auto-merge.
