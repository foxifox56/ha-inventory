# HA Inventory

HA Inventory ist eine lokale, modulare Lagerverwaltung für Home Assistant. Version 0.2 gestaltet die Oberfläche für das iPhone neu, behält die Desktopansicht bei und ergänzt eine versionierte REST-API als Integrationsvertrag. Die SQLite-Datenbank bleibt auf dem Home-Assistant-Gerät.

**Ein Scan ändert niemals den Bestand.** Ein bekannter Barcode öffnet die Artikeldetails, ein unbekannter Barcode startet die Erfassung. Bestand und Mengen ändern sich nur durch eine ausdrücklich gespeicherte Bearbeitung.

## Version 0.2

- Mobile-first Lagerübersicht mit fester Navigation für Start, Suche, Scanner und Lagerorte
- Artikelkarten für Smartphones, vollwertige Desktopansicht, große Touch-Ziele und Unterstützung des System-Dark-Modes
- Lokaler ZXing-Kamera-Decoder mit manuellem Barcode-Fallback
- Versionierte API unter `/api/v1` für Artikel, Kategorien, Lagerorte, Bestandsstatus sowie Erstellen, Ändern und Löschen von Artikeln
- Dauerhafte, barcode-unabhängige IDs aus SQLite `AUTOINCREMENT`; Version-0.1-IDs werden bei Schema-Updates erhalten
- Lesezugriff über Home-Assistant-Ingress; Schreibzugriffe zusätzlich über ein kurzlebiges Schreib-Token
- Keine direkte Datenbankverbindung für andere Anwendungen und kein neu geöffneter Host-Port
- PWA- und Home-Screen-Optionen sind untersucht und in [docs/PWA-architecture.md](docs/PWA-architecture.md) verglichen. Eine vollständige PWA wird noch nicht ausgeliefert.

Die API-Spezifikation befindet sich in [docs/API.md](docs/API.md). Die längerfristige Integrationsarchitektur für Sensoren, Aktionen, Ereignisse und To-do-/Einkaufslisten steht in [docs/architecture.md](docs/architecture.md). In 0.2 ist die eigenständige HA-Integration noch nicht installierbar; sie wartet auf einen sicheren authentifizierten Integrationszugang.

## ZXing und iPhone-Kamera

`@zxing/browser` 0.2.1 ist lokal in der Anwendung gebündelt. Es gibt zur Laufzeit keinen CDN-Aufruf. Der Kamera-Scan braucht HTTPS beziehungsweise einen sicheren Browserkontext und eine Kamerafreigabe. iOS/Safari, Ingress-Pfad, Nabu Casa und iOS-Version können sich auf Kamera und Anmeldung auswirken; deshalb bleibt die manuelle Eingabe immer verfügbar. Der Scanner wurde automatisiert getestet, aber in dieser Entwicklungsrunde nicht mit einer echten iPhone-Kamera geprüft.

## Installation auf Home Assistant OS

Die Home-Assistant-App unterstützt `aarch64` und `amd64`. Für einen Raspberry Pi 4 ist **Home Assistant OS 64-bit** (`rpi4-64`/`aarch64`) erforderlich. Die nicht unterstützte 32-Bit-Architektur `armv7` ist nicht enthalten. Der Supervisor baut das Image aus der `Dockerfile`; der erste Build auf dem Pi kann einige Minuten dauern. CI baut und startet das Image für AMD64 und ARM64.

Das GitHub-Repository ist privat und kann nicht über eine normale Repository-URL aus dem App Store installiert werden. Nach der Überprüfung kannst du die geprüfte Branch lokal bereitstellen:

1. Lade `development/v0.2` als ZIP herunter und entpacke es.
2. Öffne über Samba den Home-Assistant-Ordner **`local_apps`** (im Terminal-&-SSH-Add-on: **`/local_apps`**).
3. Lege dort `ha_inventory` an und kopiere den Inhalt des Projektordners `ha_inventory/` hinein. `local_apps/ha_inventory/config.yaml` muss direkt existieren.
4. Öffne **Einstellungen → Apps**, wähle im App-Menü **Nach Updates suchen** und aktualisiere die Ansicht.
5. Installiere **HA Inventory** aus **Local apps**, starte die App und öffne ihre Web-Oberfläche.

Der aktuelle Bereitstellungspfad folgt der [offiziellen Anleitung für lokale Apps](https://developers.home-assistant.io/docs/apps/testing/). Ältere Beispiele mit `addons` beziehungsweise `/addons` verwenden einen veralteten Alias oder Container-Mount; auf dem Host ist `local_apps` der aktuelle Ordner. Der private Repository-Status verhindert aktuell automatische Updates aus einem App-Store-Repository.

**Die Entwicklungsarbeit hat keine Änderungen auf deinem produktiven Home Assistant oder Raspberry Pi vorgenommen.** Die Schritte oben verändern das System und sind nur für einen späteren, von dir gewünschten Test gedacht.

### Sicherung

Die App nutzt `backup: cold`. Home Assistant stoppt den Container während der Sicherung; die Oberfläche ist in dieser Zeit kurz nicht verfügbar. SQLite und WAL-Dateien werden aus dem gestoppten App-Datenverzeichnis gesichert, sodass keine laufenden Datenbank-Schreibvorgänge parallel stattfinden. Die Datenbank liegt unter `/data/inventory.sqlite3`.

## Lokal entwickeln

Voraussetzung: Python 3.12 oder neuer und Node.js für die Frontend-Tests. Die Python-Backendtests verwenden nur die Standardbibliothek.

```bash
cd ha_inventory
INVENTORY_DATA_DIR=../.local-data INVENTORY_ALLOW_DIRECT_ACCESS=1 python3 -m backend
```

Öffne `http://127.0.0.1:8099`. `INVENTORY_ALLOW_DIRECT_ACCESS=1` ist nur für lokale Entwicklung; in Home Assistant bleiben alle Anfragen auf Ingress beschränkt. Kamera-Zugriff über localhost funktioniert nur, wenn der Browser den lokalen Ursprung als sicheren Kontext behandelt.

## REST API und Zugriffsschutz

Neue Clients verwenden `/api/v1`. Ingress erledigt die Home-Assistant-Authentifizierung; die App weist direkte LAN-Anfragen ab. `POST`, `PATCH` und `DELETE` benötigen darüber hinaus ein kurzlebiges Schreib-Token von `GET /api/v1/write-session`. Es ist ein zusätzlicher Schutz gegen unbeabsichtigte Cross-Site-Schreibzugriffe, kein API-Schlüssel für den Zugriff außerhalb von Ingress. Es wird weder ein offener Port noch ein externer API-Token eingerichtet. Details und Endpunkte: [docs/API.md](docs/API.md).

Die App-API ist unabhängig von der Web-Oberfläche. Andere Anwendungen verwenden ausschließlich diese API und nicht SQLite. Ein späterer HA-Client braucht einen geprüften, HA-authentifizierten Integrationspfad; `SUPERVISOR_TOKEN` wird nicht in den Browser weitergegeben. Einkaufslisten, To-do-Listen, Sensoren, Aktionen und Ereignisse sind geplant, aber in 0.2 noch nicht implementiert.

## Tests

```bash
cd ha_inventory
python3 -m unittest discover -s backend/tests -v
node --test frontend/tests/*.test.mjs
python3 -m compileall -q backend
node --check frontend/app.js
node --check frontend/vendor/zxing-browser.mjs
```

Der Container-Smoke-Test prüft Ingress, API-Schreibsitzungen und persistente SQLite-Daten nach einem Container-Neustart. Mit installiertem Docker läuft er aus dem Repository-Root:

```bash
bash scripts/container-smoke.sh
```

CI führt den Smoke-Test für `linux/amd64` und `linux/arm64` aus. Der Testbericht mit den aktuellen Ergebnissen steht in [TESTING.md](TESTING.md). Ein echter Supervisor-/Pi-Test wird bewusst nicht durchgeführt.

## Projektstruktur

```text
AGENTS.md                         Architektur- und Entwicklungsregeln
docs/API.md                       REST-API-Vertrag v1
docs/architecture.md              Datenfluss und HA-Integration
docs/PWA-architecture.md          iOS-/Ingress-/PWA-Vergleich
custom_components/ha_inventory/   Dokumentierter Platz der späteren Integration
ha_inventory/
  config.yaml                     Home-Assistant-App-Konfiguration
  backend/inventory/              Bestandsregeln und SQLite-Repository
  backend/web/                    REST API und statische Dateien
  backend/tests/                  Backend- und HTTP-Tests
  frontend/                       Browser-UI und ZXing-Bundle
  frontend/tests/                 Node-Tests für Bestand, Navigation und Scanner
```

## Bestandsmodelle

`simple` verwaltet unbekannt/vorhanden/nicht vorhanden, `inventory` eine geschätzte Menge und `exact` einen manuell gezählten Stand. `quantity: null` bedeutet unbekannt; eine erfasste `0` bedeutet bekannter Nullbestand. Barcodes werden als Text gespeichert, damit führende Nullen erhalten bleiben.

## Branch und Review

Version 0.2 wird auf `development/v0.2` entwickelt und in einem eigenen Pull Request gegen den geprüften Stand `development/v0.1` zur Überprüfung vorgelegt. Es gibt keinen automatischen Merge nach `main`.
