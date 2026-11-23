# Development guide

## Architecture

- `ha_inventory/backend/inventory/` owns inventory rules and persistence. Keep HTTP concerns out of this package.
- `ha_inventory/backend/web/` translates HTTP requests into service calls and serves the static frontend.
- `ha_inventory/frontend/` is a browser-only client. It talks to the backend through `/api`; it never reads or writes the database directly.
- `ha_inventory/backend/database.py` owns schema initialization and migrations. Persist app data only in the Home Assistant `/data` mount.
- Home Assistant packaging stays in `ha_inventory/config.yaml` and `ha_inventory/Dockerfile`. Do not require privileged mode, host networking, or access to the Home Assistant configuration directory.

## Product rules

- A barcode identifies an inventory item. Scanning it may open an existing item or start a new item form.
- Scanning must never decrement, increment, or otherwise change stock automatically.
- Stock changes happen only after a user explicitly saves an item edit.
- Represent presence-only, estimated inventory, and exact manual counts as distinct tracking modes. A missing count must remain explicitly unknown, never be represented as zero or one.
- Keep product lookup and other remote integrations optional. The app must remain usable on the local network without a cloud account.

## Development guidelines

- Keep modules small and focused; add domain behavior to the service layer, not HTTP handlers or browser code.
- Use parameterized SQL, validate all API input, and escape user-provided values before rendering HTML.
- Preserve leading zeroes in barcodes and treat barcodes as strings.
- Add a database migration when changing the schema; do not edit existing migrations.
- Use the Python standard library unless an additional dependency has a clear user-facing benefit.
- Keep the UI usable on phone-sized screens and provide manual barcode entry when camera scanning is unavailable.
- Add or update backend `unittest` and frontend Node test coverage for behavior changes. From `ha_inventory/`, run `python3 -m unittest discover -s backend/tests -v` and `node --test frontend/tests/*.test.mjs` before submitting.
- Update the README and `TESTING.md` when setup, behavior, or verification changes.
- Never install or configure this app on the user's production Home Assistant during development. Use local tests or an isolated test environment.
- Work on a development branch and leave integration into `main` for review.
