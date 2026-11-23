# Development guide

## Architecture

- `ha_inventory/backend/inventory/` owns inventory rules and persistence. Keep HTTP concerns out of this package.
- `ha_inventory/backend/product_lookup/` owns provider protocols, remote product parsing, source attribution, cache and network safety. It must call the local inventory first through the product lookup service and never persist a result.
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
- Scanning must never create an item or decrement, increment, or otherwise change stock automatically. Known codes open item details; external matches are editable suggestions and require explicit save.
- Product lookup results are suggestions only. An unknown barcode can prefill editable name, brand, pack size, category, and image fields, but only an explicit protected save may create an item. A lookup must never mutate stock.
- External providers run only on the backend. Require HTTPS, a clear User-Agent, bounded timeouts/response bodies/cache, validated redirects and image/source URLs, and graceful provider failures. Respect provider rate limits without blocking a backend worker; expose retry guidance so the frontend can perform only bounded, cancellable waits and retain a manual fallback. Do not send locations, quantities, or other inventory data to a product provider. Keep provider-specific details out of the UI and SQLite layer.
- Preserve source attribution and image licensing when external metadata is saved or shown. Treat external data as unverified user-contributed suggestions.
- Stock changes happen only after a user explicitly saves an item edit. Shopping/to-do completion and future HA events must never alter inventory silently.
- Represent presence-only, estimated inventory, and exact manual counts as distinct tracking modes. A missing count remains explicitly unknown, never zero or one.
- Keep product lookup and other remote integrations optional. The app must remain usable without a cloud database or cloud product account.
- Before enabling a future external client, define least-privilege authentication, revocation, and session handling. Never use direct SQLite access to avoid this work.

## Development guidelines

- Keep modules small and focused; add domain behavior to the service layer, not HTTP handlers or browser code.
- Use parameterized SQL, validate all API input, and escape user-provided values before rendering HTML.
- Preserve leading zeroes in barcodes and treat barcodes as strings.
- Add a database migration when changing the schema; do not edit existing migrations.
- Product metadata migrations must be additive and must preserve legacy item IDs, barcodes, notes, locations, and confirmed stock values.
- Use the Python standard library unless an additional dependency has a clear user-facing benefit. Vendor browser dependencies locally, pin the version, and include license notices.
- Keep the UI mobile-first, retain a usable desktop layout, provide manual barcode entry, honor reduced motion, and support system Dark Mode.
- A PWA manifest, service worker, standalone metadata, or alternate iPhone auth flow may only be added after `docs/PWA-architecture.md`'s security questions are resolved and documented.
- Keep shopping-list operations explicit and idempotent. Check for duplicates before writing, and never change inventory when a to-do item is completed.
- Add/update backend `unittest` and frontend Node test coverage for behavior changes. From `ha_inventory/`, run:

  ```bash
  python3 -m unittest discover -s backend/tests -v
  node --test frontend/tests/*.test.mjs
  python3 -m compileall -q backend
  node --check frontend/app.js
  ```

- Product lookup tests must cover local-first behavior, all enabled provider types, missing fields/images, network/timeout/schema failures, leading-zero barcodes, cache/rate behavior, and proof that a lookup does not create or alter an item. Frontend tests must cover suggestions, manual fallback, loading and single explicit-save semantics.

- Update `README.md`, `TESTING.md`, `docs/API.md`, and architecture notes when setup, API behavior, security, or verification changes.
- Never install or configure this app on the user's production Home Assistant during development. Use local tests or an isolated test environment.
- Work on a development branch and leave integration into `main` for review. Do not configure auto-merge.
