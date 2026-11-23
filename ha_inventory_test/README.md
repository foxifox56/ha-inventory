# HA Inventory TEST

Separat installierbare Test-App für v0.4 mit eigenem Slug `ha-inventory-test` und eigenem Datenbestand. Sie startet nicht automatisch und hat keine Host-Portfreigabe.

**Vor Installation:** [Sicherheits- und Installationshinweise](DOCS.md) lesen. Die reguläre App `ha-inventory` nicht ersetzen oder entfernen.

Entwickler: Laufzeitcode ausschließlich in `ha_inventory/` bearbeiten, anschließend `python scripts/sync-test-app.py --sync` ausführen. CI prüft Bytegleichheit über `--check`. Nur `config.yaml`, `DOCS.md` und `README.md` sind bewusst unterschiedlich.
