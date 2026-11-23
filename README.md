# HA Inventory

HA Inventory ist eine lokale, modulare Lagerverwaltung für Home Assistant. Version 0.4 ergänzt den Barcode-Workflow um ein iPhone-taugliches Kassenbonfoto, lokale Tesseract-OCR und eine gemeinsam bestätigte, rückgängig machbare Übernahme. Die SQLite-Datenbank bleibt auf dem Home-Assistant-Gerät.

**Standardmäßig ist der Scan-Modus „Ansehen“ und verändert nichts.** Ein bekannter numerischer oder alphanumerischer Artikelcode öffnet die vorhandenen Artikeldetails. Im ausdrücklich ausgewählten Modus „Verbrauchen“ bucht ein Scan die gewählte Packungsanzahl (Standard: eine Packung) für einen Artikel mit bekanntem Zahlenbestand. „Einlagern“ verlangt immer eine Bestätigung. Unbekannte Produkte durchlaufen weiterhin die Produkterkennung aus v0.2; das Speichern und eine etwaige Startbestandsbuchung sind getrennte bestätigte Schritte.

## Version 0.3

- Mobile-first Lagerübersicht mit fester Navigation für Start, Suche, Scanner, Lagerorte und Kassenbon
- Artikelkarten für Smartphones, vollwertige Desktopansicht, große Touch-Ziele und Unterstützung des System-Dark-Modes
- Lokaler ZXing-Kamera-Decoder mit manuellem Barcode-Fallback
- Lokaler Datenbanktreffer vor externer Produktsuche über Open Food Facts, Open Beauty Facts, Open Pet Food Facts und Open Products Facts
- Erkannte Produktdaten (Name, Marke, Packungsgröße, Kategorie und gegebenenfalls Bild) werden als editierbare Vorschläge angezeigt; gespeichert wird erst nach „Artikel speichern“
- Versionierte API unter `/api/v1` für Artikel, Kategorien, Lagerorte, Bestandsstatus sowie Erstellen, Ändern und Löschen von Artikeln
- Dauerhafte, barcode-unabhängige IDs aus SQLite `AUTOINCREMENT`; Version-0.1-IDs werden bei Schema-Updates erhalten
- Lesezugriff über Home-Assistant-Ingress; Schreibzugriffe zusätzlich über ein kurzlebiges Schreib-Token
- Keine direkte Datenbankverbindung für andere Anwendungen und kein neu geöffneter Host-Port
- Scan-Modi **Ansehen**, **Einlagern** und **Verbrauchen**; Ansehen ist Standard und bleibt rein lesend
- Schnelles Einlagern mit editierbarer Packungsanzahl und ausdrücklicher Bestätigung
- Verbrauchsmodus bucht standardmäßig eine Packung je Scan; eine größere ganze Anzahl kann vor dem Scan ausgewählt werden
- Transaktionale und idempotente Bestandsbuchungen mit Schutz vor Doppelbuchungen, negativen Beständen und parallelem Überziehen
- Dauerhafter Verlauf je Artikel; Rückgängig ist eine eigene Gegenbuchung und pro Buchung nur einmal möglich
- SQLite-Migration v5 ergänzt die Buchungstabelle; v6 baut nur diese Tabelle datengetreu um, damit bestätigte Nullbestände journalisiert werden können. Artikel- und Bewegungs-IDs bleiben erhalten.
- Ein unbekannter oder einfacher Bestand muss ausdrücklich als Startbestand initialisiert werden, bevor er numerisch gebucht werden kann; ein bestätigter Startbestand von `0` ist bekannt und von `null` (unbekannt) unterscheidbar
- Unsichere Wiederholungen nach einem Verbindungsabbruch verwenden denselben gespeicherten Idempotenzschlüssel, damit eine bereits bestätigte Buchung nicht doppelt angewendet wird
- PWA- und Home-Screen-Optionen sind untersucht und in [docs/PWA-architecture.md](docs/PWA-architecture.md) verglichen. Eine vollständige PWA wird noch nicht ausgeliefert.

## Version 0.4

- Fotoaufnahme direkt aus der iPhone-Kamera oder Auswahl aus der Mediathek; Bild drehen, zuschneiden und im Browser verkleinern
- Lokale Texterkennung mit Tesseract `deu` + `eng` und Pillow im Home-Assistant-App-Container; keine Cloud-OCR und kein dauerhaftes Speichern des Fotos oder OCR-Volltexts
- REWE- und Kaufland-orientierte Erkennung von Artikeln, Preisen, Mehrfachmengen, Datum, Summe und Händler; Pfand, Rückgaben, Rabatte, Summen und Zahlungsdaten werden möglichst herausgefiltert
- Erkannte Positionen bleiben vor dem Import bearbeitbar. Katalogvorschläge und benutzergelernte Händler-Aliase helfen bei der Zuordnung; unbekannte Produkte werden nur nach ausdrücklicher Auswahl angelegt
- Mengen- und Zuordnungsprüfung, Dublettenhinweis über Bildhash und Bon-Fingerprint sowie ausdrückliche Ausnahmebestätigung bei erneutem Import. Eine unklare Menge bleibt leer und muss vor dem Import eingetragen werden.
- Mehrzeilige REWE-/Kaufland-Mengen wie `MILCH 1,09` gefolgt von `2 x 1,09 2,18` werden als zwei Packungen erkannt; unterbrochene/mehrdeutige Zuordnungen sind sichtbar prüfpflichtig.
- Ein Foto-Wechsel oder Abbruch entwertet laufende Bildverarbeitung/OCR; verspätete Antworten des vorherigen Fotos werden verworfen.
- Sammelimport nur nach Bestätigung; alle Buchungen und neu angelegten Artikel laufen atomar über `StockMovementService`. Idempotenzschlüssel schützen Wiederholungen nach Verbindungsabbrüchen.
- Die Bestandsbuchungen eines Bons können atomar gemeinsam rückgängig gemacht werden. **Neu angelegte Artikel bleiben mit unbekanntem Bestand erhalten; gelernte Produktzuordnungen bleiben gespeichert.** Wenn spätere Buchungen ein sicheres Undo verhindern, bleibt der komplette Bestand unverändert.
- Additive SQLite-Migration v7 für Bon-Metadaten, Händler-Aliase und Verknüpfungen zum Buchungsverlauf; vorhandene Artikel- und Bewegungs-IDs bleiben erhalten
- Home-Assistant-Container enthält Tesseract sowie deutsche und englische Sprachdaten für `amd64` und `aarch64`; CI-Smoke prüft tatsächliche OCR mit einem synthetischen Bon

Die Erkennung ist ein Vorschlag. Bonlayouts, Abkürzungen, schlechte Fotos, Aktionspreise und Händler-Varianten können zu fehlenden oder falschen Positionen führen. Jede Zeile und Menge muss vor dem Import geprüft werden. Einzelpreise werden nie als Stückzahl verwendet; wenn die Menge nicht eindeutig erkannt wird, muss sie geprüft werden. Unbekannte oder einfache Bestände benötigen weiterhin eine ausdrückliche Wahl des Bestandsmodells.

Die API-Spezifikation einschließlich Produktsuche befindet sich in [docs/API.md](docs/API.md). Die längerfristige Integrationsarchitektur für Sensoren, Aktionen, Ereignisse und To-do-/Einkaufslisten steht in [docs/architecture.md](docs/architecture.md). In 0.2 ist die eigenständige HA-Integration noch nicht installierbar; sie wartet auf einen sicheren authentifizierten Integrationszugang.

## ZXing und iPhone-Kamera

`@zxing/browser` 0.2.1 ist lokal in der Anwendung gebündelt. Es gibt zur Laufzeit keinen CDN-Aufruf. Der Kamera-Scan braucht HTTPS beziehungsweise einen sicheren Browserkontext und eine Kamerafreigabe. iOS/Safari, Ingress-Pfad, Nabu Casa und iOS-Version können sich auf Kamera und Anmeldung auswirken; deshalb bleibt die manuelle Eingabe immer verfügbar. Die Kamera wurde automatisiert mit Mocks getestet, aber in dieser Entwicklungsrunde nicht mit einem echten iPhone geprüft. Vor einer Aussage zur iPhone-Tauglichkeit muss die manuelle Checkliste in [TESTING.md](TESTING.md) auf iPhone und Home Assistant ausgeführt werden.

## Automatische Produkterkennung

Der Browser sendet nur den Barcode an `GET /api/v1/product-lookup/{barcode}`. Das Backend prüft zuerst die lokale SQLite-Datenbank und fragt nur bei einem lokalen Fehltreffer die gemeinsame Open-Facts-Barcode-API über HTTPS ab. Das API-`product_type=all` deckt Lebensmittel, Kosmetik, Tiernahrung und allgemeine Produkte ab. Das Antwortfeld `product_type` ordnet die Quelle und eine passende Standardkategorie zu. Siehe die [Open Facts API-Dokumentation](https://openfoodfacts.github.io/openfoodfacts-server/api/) und die Dokumentation zur [universellen Barcode-Suche](https://openfoodfacts.github.io/openfoodfacts-server/api/tutorials/scanning-cosmetics-pet-food-and-other-products/).

Die API-Daten sind freiwillige Community-Daten und können fehlen, veraltet oder falsch sein. Das Formular bleibt bearbeitbar und zeigt Datenquelle sowie Lizenzhinweis zur Produktabbildung. Bilder werden nur von HTTPS-Hosts des Open-Facts-Ökosystems geladen. Die API nennt 15 Produkt-Leseanfragen pro IP und Minute; HA Inventory begrenzt ungecachete externe Anfragen zusätzlich auf höchstens eine Anfrage in 4,1 Sekunden und hält höchstens 256 Cacheeinträge im Arbeitsspeicher (Treffer sechs Stunden, Nichttreffer fünf Minuten). Bei einem zu frühen Folgeabruf antwortet das Backend sofort mit Retry-Hinweis statt im Rate-Limit zu warten. Das Frontend versucht höchstens zweimal und wartet insgesamt höchstens zwölf Sekunden wegen des Rate-Limits; die Anbieterabfragen selbst haben jeweils ein fünfsekündiges Timeout. Die Wartezeit kann jederzeit abgebrochen werden. Bei Providerfehlern bleibt die lokale Lagerverwaltung nutzbar und die Oberfläche bietet „Erneut versuchen“ oder „Manuell erfassen“.

Open Facts nennt ODbL für die Datenbank, eine Database Contents License für einzelne Inhalte und CC BY-SA für Produktbilder. Bei Speicherung eines erkannten Vorschlags bleiben Quelle, Produktseite und Bildlizenz erhalten; der UI-Hinweis verlinkt auf die Quelle. Es werden keine Lagerorte, Mengen oder persönlichen Bestandsdaten an Open Facts übertragen. Prüfe und korrigiere Vorschläge vor dem Speichern. Weitere Provider können über `backend/product_lookup` ergänzt werden, ohne UI oder SQLite direkt an einen Anbieter zu koppeln. Details: [docs/architecture.md](docs/architecture.md), [docs/API.md](docs/API.md).

## Installation auf Home Assistant OS

Die Home-Assistant-App unterstützt `aarch64` und `amd64`. Für einen Raspberry Pi 4 ist **Home Assistant OS 64-bit** (`rpi4-64`/`aarch64`) erforderlich. Die nicht unterstützte 32-Bit-Architektur `armv7` ist nicht enthalten. Der Supervisor baut das Image aus der `Dockerfile`; der erste Build auf dem Pi kann wegen Tesseract, Sprachdaten und Pillow einige Minuten dauern. CI baut und startet das Image für AMD64 und ARM64 und prüft lokale OCR.

Das GitHub-Repository ist öffentlich. Der Review-Branch kann im Home-Assistant-App-Store als Repository mit Branch-Suffix hinzugefügt werden:

```text
https://github.com/foxifox56/ha-inventory#development/v0.4
```

In Home Assistant: **Einstellungen → Apps → Installieren → ⋮ → Repositories**, URL hinzufügen und danach **HA Inventory** aus diesem Repository auswählen. Die offizielle [Home Assistant-Anleitung zu App-Repositories](https://developers.home-assistant.io/docs/apps/guides/repository/) bestätigt `#branch` als Weg, einen anderen Branch als den Standardbranch auszuwählen. `development/v0.4` ist ein Review-Branch und kann sich ändern.

**Daten und Upgrade:** Vor jedem Upgrade ein vollständiges Home-Assistant-Backup mit App-Daten erstellen und außerhalb des Geräts ablegen. `backup: cold` sichert SQLite bei gestopptem App-Container. Der Supervisor verwendet die Repository-URL einschließlich Branch für die Repository-ID; ein Wechsel von lokaler Installation oder anderem Branch kann daher eine andere App-ID und ein anderes `/data` erzeugen. Die vorhandene Datenbank wird dann nicht automatisch übernommen. Installiere den Review-Branch nicht parallel zu einem produktiven Bestand und kopiere keine laufende SQLite-Datei. Ein Update derselben App-Identität nutzt den vorhandenen App-Datenspeicher; ein Backup-/Restore zwischen unterschiedlichen App-IDs wurde hier nicht auf einem Supervisor geprüft. Vor einem Branch-Wechsel muss der unterstützte Backup-/Restore-Pfad auf einer separaten HA-Testinstanz verifiziert werden. Beim Rollback zuerst die Test-App stoppen und den Restore-Pfad prüfen; die bisherige App nicht entfernen, bevor Daten und Rückkehrweg geprüft sind.

Lokale Entwicklung folgt weiterhin der [offiziellen Anleitung für lokale Apps](https://developers.home-assistant.io/docs/apps/testing/): Host-Ordner `local_apps`, darin `ha_inventory/config.yaml`. Die lokale Entwicklungsinstallation und das öffentliche Git-Repository sind getrennte Supervisor-Repositories.

**Die Entwicklungsarbeit hat keine Änderungen auf deinem produktiven Home Assistant oder Raspberry Pi vorgenommen.** Die Schritte oben verändern das System und sind nur für einen späteren, von dir gewünschten Test gedacht.

### Sicherung

Die App nutzt `backup: cold`. Home Assistant stoppt den Container während der Sicherung; die Oberfläche ist in dieser Zeit kurz nicht verfügbar. SQLite und WAL-Dateien werden aus dem gestoppten App-Datenverzeichnis gesichert, sodass keine laufenden Datenbank-Schreibvorgänge parallel stattfinden. Die Datenbank liegt unter `/data/inventory.sqlite3`. Bonfotos und OCR-Volltexte liegen nicht in der Datenbank; für erkannte/importierte Bons bleiben nur Hashes, Status, Fingerprint und Buchungsverknüpfungen.

## Lokal entwickeln

Voraussetzung: Python 3.12 oder neuer, Node.js für die Frontend-Tests sowie Pillow für die lokale Bildverarbeitung.

```bash
cd ha_inventory
python3 -m pip install -r requirements.txt
INVENTORY_DATA_DIR=../.local-data INVENTORY_ALLOW_DIRECT_ACCESS=1 python3 -m backend
```

Öffne `http://127.0.0.1:8099`. `INVENTORY_ALLOW_DIRECT_ACCESS=1` ist nur für lokale Entwicklung; in Home Assistant bleiben alle Anfragen auf Ingress beschränkt. Kamera-Zugriff über localhost funktioniert nur, wenn der Browser den lokalen Ursprung als sicheren Kontext behandelt.

## REST API und Zugriffsschutz

Neue Clients verwenden `/api/v1`. Ingress erledigt die Home-Assistant-Authentifizierung; die App weist direkte LAN-Anfragen ab. `POST`, `PATCH` und `DELETE` benötigen darüber hinaus ein kurzlebiges Schreib-Token von `GET /api/v1/write-session`. Es ist ein zusätzlicher Schutz gegen unbeabsichtigte Cross-Site-Schreibzugriffe, kein API-Schlüssel für den Zugriff außerhalb von Ingress. Es wird weder ein offener Port noch ein externer API-Token eingerichtet. Details und Endpunkte: [docs/API.md](docs/API.md).

Die App-API ist unabhängig von der Web-Oberfläche. Andere Anwendungen verwenden ausschließlich diese API und nicht SQLite. Ein späterer HA-Client braucht einen geprüften, HA-authentifizierten Integrationspfad; `SUPERVISOR_TOKEN` wird nicht in den Browser weitergegeben. Einkaufslisten, To-do-Listen, Sensoren, Aktionen und Ereignisse sind geplant, aber noch nicht implementiert.

## Tests

```bash
cd ha_inventory
python3 -m unittest discover -s backend/tests -v
node --test frontend/tests/*.test.mjs
python3 -m compileall -q backend
node --check frontend/app.js
node --check frontend/api-client.mjs
node --check frontend/product-prefill.mjs
node --check frontend/stock-booking.mjs
node --check frontend/receipt-flow.mjs
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
  backend/inventory/              Artikeldaten, Buchungen und SQLite-Repository
  backend/web/                    REST API und statische Dateien
  backend/tests/                  Backend- und HTTP-Tests
  frontend/                       Browser-UI, Buchungsablauf und ZXing-Bundle
  frontend/tests/                 Node-Tests für Bestand, Navigation, Scanner und Buchungen
```

## Bestandsmodelle

`simple` verwaltet unbekannt/vorhanden/nicht vorhanden, `inventory` eine geschätzte Menge und `exact` einen manuell gezählten Stand. `quantity: null` bedeutet unbekannt; eine erfasste `0` bedeutet bekannter Nullbestand. Barcodes werden als Text gespeichert, damit führende Nullen erhalten bleiben.

## Branch und Review

Version 0.4 wird auf `development/v0.4` entwickelt und als eigener Pull Request gegen `development/v0.3` zur Überprüfung vorgelegt. Es gibt keinen automatischen Merge nach `main`.


## Separat installierbare Test-App (v0.4)

Der Review-Branch `development/v0.4-test-app` enthält neben der unveränderten regulären App in `ha_inventory/` die separate `ha_inventory_test/` mit dem **eigenen Slug `ha-inventory-test`**, einem unabhängigen persistenten App-`/data`-Verzeichnis und `boot: manual`. Kein freigegebener Host-Port. Dadurch wird die reguläre App-Datenbank nicht gemeinsam genutzt. Die Test-App ist zunächst leer und enthält keine Produktivdaten.

**Bitte nicht über eine Änderung des installierten App-Branches aktualisieren!** Vor einem Test ein HA-Backup inklusive Apps erstellen; anschließend nur `ha-inventory-test` auswählen. Installation alternativ über `local_apps/ha_inventory_test`; weitere Details in [ha_inventory_test/DOCS.md](ha_inventory_test/DOCS.md). Ein echter HAOS-/Supervisor-Laufzeittest steht noch aus.

Der Test-Code ist absichtlich eine vollständige, eigenständig baubare Kopie des v0.4-Codes. Nach Änderungen an `ha_inventory/` synchronisiert `python scripts/sync-test-app.py --sync` die Test-App, `--check` erzwingt Bytegleichheit im CI-Workflow. Kein Merge/Deployment wird automatisch durchgeführt.
