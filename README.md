# HA Inventory

Eine lokale, universelle Lagerverwaltung als Home-Assistant-App. Version 0.1 bietet Artikelsuche, Barcode-Zuordnung, Kategorien, Lagerorte und einen manuell gepflegten Bestand.

**Scannen verändert den Bestand nicht.** Ein bereits bekannter Barcode öffnet den vorhandenen Artikel; ein unbekannter Barcode startet die Erfassung. Mengen werden nur geändert, wenn du sie im Artikel ausdrücklich anpasst und speicherst.

## Funktionen in Version 0.1

- Artikel für Lebensmittel, Werkzeuge, Haushaltsartikel und weitere Kategorien erfassen
- Artikel über Namen oder Barcode suchen
- Kamera-Barcode-Scan in unterstützten Browsern, zusätzlich manuelle Eingabe und USB-/Bluetooth-Scanner
- Bestand, Einheit, Lagerort und optionale Mindestmenge hinterlegen
- Niedrige Bestände und Kategorien in der Übersicht erkennen
- Änderungen lokal in SQLite speichern; keine Cloud und kein bPlaced-Konto erforderlich
- Home-Assistant-Oberfläche über Ingress öffnen

## Installation auf Home Assistant OS

Die Entwicklungsfassung wird auf dem Home Assistant OS installiert und baut ihr Image dort. Der erste Build kann auf einem Raspberry Pi einige Minuten dauern. Die Datenbank liegt dauerhaft im App-Datenverzeichnis und wird vom Home-Assistant-Backup erfasst.

1. Öffne **Einstellungen → Apps → App installieren**.
2. Öffne oben rechts das Menü **Repositories**.
3. Füge diese Repository-Adresse ein, einschließlich Entwicklungsbranch:

   `https://github.com/foxifox56/ha-inventory#development/v0.1`

4. Aktualisiere die App-Liste, wähle **HA Inventory** und installiere die App.
5. Starte sie und öffne **Web-Oberfläche öffnen**.

Home Assistant OS auf einem Raspberry Pi 4 mit 64-Bit-System (`aarch64`) wird unterstützt. `armv7` ist für 32-Bit-Installationen eingetragen, sofern das verwendete Python-Basisimage diese Architektur bereitstellt. `amd64` ist für Entwicklungs- und Testsysteme enthalten.

### Barcode-Scan mit der Handykamera

Der Kamera-Scan benötigt einen Browser mit `BarcodeDetector` und einen sicheren Web-Kontext. Das ist normalerweise bei HTTPS-Zugriff auf Home Assistant gegeben. Falls der Browser keine Kamera freigibt, kannst du den Code im Scan-Dialog eintippen oder einen Bluetooth-/USB-Scanner verwenden, der den Code wie Tastatureingaben sendet.

## Lokal starten

Voraussetzung: Python 3.12 oder neuer. Es gibt keine externen Python-Pakete.

```bash
cd ha_inventory
INVENTORY_DATA_DIR=../.local-data INVENTORY_ALLOW_DIRECT_ACCESS=1 python3 -m backend
```

Danach im Browser `http://127.0.0.1:8099` öffnen. `INVENTORY_ALLOW_DIRECT_ACCESS=1` ist ausschließlich für lokale Entwicklung gedacht. Die Home-Assistant-App akzeptiert standardmäßig nur Anfragen über den Ingress-Proxy.

## Tests

```bash
cd ha_inventory
python3 -m unittest discover -s backend/tests -v
```

Siehe [TESTING.md](TESTING.md) für die zuletzt ausgeführten Prüfungen.

## Projektstruktur

```text
AGENTS.md                  Architektur- und Entwicklungsregeln
repository.yaml            Home-Assistant-App-Repository-Metadaten
ha_inventory/
  config.yaml              Home-Assistant-App-Konfiguration
  Dockerfile               Multi-Architektur-Image für HA OS
  backend/
    inventory/             Bestandsregeln und Repository
    web/                   HTTP API und statische Auslieferung
    tests/                 Unit- und HTTP-Integrationstests
  frontend/                Responsive Web-Oberfläche
```

## Datenmodell

Ein Artikel enthält Name, optional eindeutigen Barcode, Kategorie, Menge, Einheit, Lagerort, Mindestmenge, Notiz und Zeitstempel. Der Barcode wird als Text gespeichert, damit führende Nullen erhalten bleiben. Änderungen des Bestands werden nicht aus Scan-Vorgängen abgeleitet.

## Grenzen von Version 0.1

- Produktnamen werden nicht automatisch aus einem Online-Katalog geladen; ein unbekannter Artikel wird einmal manuell benannt.
- Mengenverbrauch wird nicht automatisch erfasst.
- Es gibt noch keine Home-Assistant-Entitäten, Benachrichtigungen, Mehrbenutzerrechte oder bPlaced-Anbindung.
- Die Datenbank bleibt vollständig lokal in der App.

## Entwicklung

Die Anwendung wird auf `development/v0.1` entwickelt und zur Überprüfung als Pull Request angeboten. `main` enthält derzeit nur den Repository-Startpunkt.
