# Testprotokoll

Stand: 23.11.2026, Branch `development/v0.2`. Automatisierte Prüfungen verwenden ausschließlich temporäre SQLite-Datenbanken und gemockte Provider-Antworten. Es werden keine Produktdaten von Open Facts während Tests angefragt.

## Automatisierte Prüfungen

| Prüfung | Umfang |
| --- | --- |
| Backend-Unit-, Migrations- und HTTP-Tests | API v1, Ingress, lokale Treffer, Anbieter-Fallback, Metadatenvalidierung, Fehler, Schreibschutz und Datenbankpersistenz |
| Provider-Tests | vier Open-Facts-Produktarten, benutzerdefinierter Folgeprovider, optionale Felder/Bilder, führende Nullen, ungültige JSON-/HTTP-Antworten, Timeouts, Rate-Limits, Cache und Redirect-Allowlist |
| Frontend-Tests | automatische Formularvorschläge, fehlende Daten, unbekannter Barcode, Lade-/Abschlusszustand und Bestandsschutz |
| API-Client-Tests | abgelaufenes Token genau einmal erneuern; `403` von Ingress nicht als Tokenablauf behandeln; keine endlose Wiederholung |
| Migrationstests | v1-Altbestand und v3-Bestand: IDs, Barcodes, Notizen und bestätigte Mengen bleiben bei der additiven v4-Migration erhalten |
| Python/JavaScript-Syntax | `compileall` sowie `node --check` für App und Laufzeitmodule |
| Lokale Ergebniszahlen | 38 Backendtests und 19 Frontendtests bestanden; YAML von App, Repository und Actions geparst |
| Docker lokal | Nicht ausführbar: Docker-CLI ist in dieser Umgebung nicht installiert |
| Docker-Smoke-Tests | Containerstart, Ingress/API, Schreibsitzung und persistente `/data`-Daten auf AMD64 und ARM64 (GitHub Actions) |

Aus `ha_inventory/` ausführen:

```bash
python3 -m unittest discover -s backend/tests -v
node --test frontend/tests/*.test.mjs
python3 -m compileall -q backend
node --check frontend/app.js
node --check frontend/api-client.mjs
node --check frontend/product-prefill.mjs
node --check frontend/barcode-lookup.mjs
node --check frontend/mobile-navigation.mjs
node --check frontend/zxing-scanner.mjs
node --check frontend/vendor/zxing-browser.mjs
```

Der Docker-Smoke-Test wird aus dem Repository-Root gestartet:

```bash
bash scripts/container-smoke.sh
INVENTORY_SMOKE_PLATFORM=linux/arm64 bash scripts/container-smoke.sh
```

Die GitHub-Actions-Ergebnisse für diesen Änderungsstand werden nach dem Push ergänzt. Der vorherige v0.2-Stand bestand im Workflow-Lauf [#10](https://github.com/foxifox56/ha-inventory/actions/runs/45182976094); dieser ältere Lauf deckt die neue Produkterkennung noch nicht ab.

## Manueller Ende-zu-Ende-Test auf einem iPhone

Dieser Test wurde in dieser Entwicklungsumgebung nicht ausgeführt. Er benötigt ein iPhone, Home Assistant über lokale HTTPS-URL oder Nabu Casa und eine separat eingerichtete HA-Testinstanz. Vor einer Produktivinstallation ist der Kamera-Test zu erledigen.

1. HA Inventory über **Home Assistant → Einstellungen → Apps → HA Inventory → Öffnen** starten. Nicht aus einer ungeschützten Direktadresse öffnen.
2. Scanner antippen, bei Aufforderung Kamerazugriff erlauben und Rückkamera verifizieren. Browser muss HTTPS und Kamera im Ingress-Kontext unterstützen.
3. Einen bereits gespeicherten Barcode scannen. Details müssen erscheinen; Menge und Status notieren und nach dem Scan vergleichen.
4. Einen Open-Facts-Testbarcode scannen, der lokal nicht existiert. Ladeanzeige prüfen; falls gefunden, Name, Marke, Packungsgröße, Kategorie, Bild, Datenquelle und Bildlizenz prüfen. Felder ändern, Lagerort und Bestandsmodell selbst wählen. Vor dem Tippen auf „Artikel speichern“ darf die Artikelliste unverändert bleiben.
5. Formular abbrechen und den Barcode erneut scannen. Prüfen, dass kein neuer Artikel angelegt wurde. Danach bewusst speichern und prüfen, dass genau ein Datensatz mit den gewählten Feldern angelegt wurde und der Bestand nur dem ausdrücklich ausgewählten Bestandsmodell entspricht.
6. Einen unbekannten Barcode scannen oder eingeben. Das normale Formular muss mit Barcode geöffnet werden. Manuelle Eingabe und Kamerascan müssen denselben Ablauf verwenden.
7. Bei laufender Kamera den Dialog schließen. Kameraindikator muss erlöschen. Kamerazugriff verweigern und einen Offline-/Timeoutfall simulieren: verständliche Meldung, manuelle Eingabe bleibt nutzbar.
8. Einen bekannten Barcode erneut scannen und die Werte mit den zuvor notierten Bestandswerten vergleichen. Ein Scan darf nie Menge, Status oder Lagerort ändern.

Für echte Produkterkennung ist eine Internetverbindung vom Home-Assistant-App-Container zu den Open-Facts-HTTPS-APIs erforderlich. Tests können mit kuratierten Beispielprodukten aus den jeweiligen Facts-Projekten erfolgen; Produktdaten sind freiwillig gepflegt und können sich ändern.

## Noch offene Hardware-/Supervisor-Checks

- iPhone-Kamera und iOS-/Ingress-/Nabu-Casa-Verhalten: manuell nach obiger Liste offen; automatisierte ZXing-Tests verwenden Kamera-Mocks.
- Home Assistant OS auf Raspberry Pi 4 `rpi4-64` / `aarch64`: ARM64 Docker-Build und Smoke-Test sind nur ein CI-Nachweis, kein Supervisor- oder Pi-Test.
- Supervisor-Backup/Restore beim Wechsel zwischen Repository-URLs/Branches mit unterschiedlicher App-ID: nicht auf Hardware ausgeführt. Vollständiges HA-Backup vor einem Upgrade erstellen; Branch-Wechsel kann ein separates `/data`-Verzeichnis bedeuten.
- PWA, Offline-Betrieb der App und eigenständiger Homescreen-Zugang: nicht implementiert. Produktsuche funktioniert offline nicht, aber manuelle Artikelerfassung bleibt verfügbar.
- Produktions-Home-Assistant und Raspberry Pi: nicht verändert; es wurde keine Installation vorgenommen.
