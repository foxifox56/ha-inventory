# Testprotokoll

Stand: 23.11.2026, Branch `development/v0.2`. Automatisierte Prüfungen verwenden ausschließlich temporäre SQLite-Datenbanken und gemockte Provider-Antworten. Es werden keine Produktdaten von Open Facts während Tests angefragt.

## Automatisierte Prüfungen

| Prüfung | Umfang |
| --- | --- |
| Backend-Unit-, Migrations- und HTTP-Tests | API v1, Ingress, lokale Treffer, Anbieter-Fallback, Metadatenvalidierung, Fehler, Schreibschutz und Datenbankpersistenz |
| Provider-Tests | vier Open-Facts-Produktarten, benutzerdefinierter Folgeprovider, optionale Felder/Bilder, führende Nullen, alphanumerische lokale Codes, ungültige JSON-/HTTP-Antworten, Timeouts, Retry-After, Cache und Redirect-Allowlist |
| Frontend-Tests | numerische und alphanumerische Codes, Formularvorschläge, mehrere Rate-Limit-Retries, abbrechbare Wartezeit, manuelle Alternative und Bestandsschutz |
| API-Client-Tests | abgelaufenes Token genau einmal erneuern; `403` von Ingress nicht als Tokenablauf behandeln; keine endlose Wiederholung |
| Migrationstests | v1-Altbestand und v3-Bestand: IDs, Barcodes, Notizen und bestätigte Mengen bleiben bei der additiven v4-Migration erhalten |
| Python/JavaScript-Syntax | `compileall` sowie `node --check` für App und Laufzeitmodule |
| Lokale Ergebniszahlen | 43 Backendtests und 25 Frontendtests bestanden; YAML von App, Repository und Actions geparst |
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

Der aktuelle Review-Korrekturstand bestand im PR-Workflow [#20](https://github.com/foxifox56/ha-inventory/actions/runs/45204403049) und Push-Workflow [#19](https://github.com/foxifox56/ha-inventory/actions/runs/45204386926). Beide liefen erfolgreich: Backend- und Frontendtests sowie Docker-Build und Smoke-Test für AMD64 und ARM64. Der lokale Docker-Smoke-Test war nicht verfügbar, da die Docker-CLI in dieser Entwicklungsumgebung nicht installiert ist.

## Manueller Ende-zu-Ende-Test auf einem iPhone

Dieser Test wurde in dieser Entwicklungsumgebung nicht ausgeführt. Er benötigt ein iPhone, eine separat eingerichtete Home-Assistant-Testinstanz und Zugriff über HTTPS. Er kann im Heim-WLAN über die HTTPS-URL von Home Assistant oder außerhalb des Hauses über die Nabu Casa Remote URL erfolgen. Beide Wege müssen HA-Login und den App-Ingress-Kontext verwenden; nicht direkt auf Add-on-IP oder -Port zugreifen.

1. In der Home-Assistant-App auf dem iPhone anmelden. Im Heim-WLAN die lokale HTTPS-URL oder außerhalb des Hauses die Nabu Casa Remote URL öffnen. Danach HA Inventory über **Einstellungen → Apps → HA Inventory → Öffnen** aufrufen. Nicht über Add-on-IP, Port oder eine direkte App-URL starten.
2. Scanner antippen und Kamerazugriff erteilen. Rückkamera prüfen. Safari beziehungsweise der Home-Assistant-In-App-Browser muss HTTPS, Anmeldung und Ingress-Sitzung beibehalten.
3. Einen bereits gespeicherten numerischen Artikelcode und einen alphanumerischen Code wie `TOOL-001` scannen. Beide müssen denselben vorhandenen Datensatz öffnen. Menge, Status und Lagerort vorher/nachher vergleichen.
4. Einen unbekannten alphanumerischen Code scannen und anschließend manuell eingeben. Beide Male muss die manuelle Artikelerfassung mit unverändertem Code öffnen, ohne Open Facts aufzurufen.
5. Einen bekannten Open-Facts-Testbarcode scannen, der lokal nicht existiert. Ladeanzeige prüfen; falls erkannt, Name, Marke, Packungsgröße, Kategorie, Bild, Quelle und Bildlizenz prüfen. Felder editieren und Lagerort/Bestandsmodell wählen. Vor „Artikel speichern“ darf kein Datensatz in der Lagerübersicht erscheinen.
6. Drei unterschiedliche, lokal unbekannte numerische Barcodes direkt nacheinander scannen. Bei Rate-Limit muss eine verständliche Warteanzeige mit automatischem begrenztem Retry erscheinen. Währenddessen „Manuell erfassen“ antippen: Warte-Retry muss abbrechen und das Formular sofort mit dem Barcode öffnen.
7. Formular abbrechen, denselben Barcode erneut scannen und prüfen, dass kein Artikel angelegt wurde. Danach bewusst einmal speichern; genau ein Datensatz muss erscheinen. Doppeltippen auf Speichern darf keine zweite Anlage erzeugen.
8. Offlinezugriff beziehungsweise einen Provider-Timeout testen. Fehlermeldung, „Erneut versuchen“ und manuelle Erfassung prüfen. Bei wiederholtem Scan eines gespeicherten Codes müssen immer dieselben Artikel-ID und Bestandswerte erscheinen.
9. Bei laufender Kamera den Dialog schließen. Kameraindikator muss erlöschen. Ein Scan darf niemals Menge, Bestandsstatus oder Lagerort ändern.

Für externe Produkterkennung braucht der App-Container eine Internetverbindung zu den Open-Facts-HTTPS-APIs. Die Kataloge sind freiwillig gepflegt; Treffer, Kategorien und Bilder können fehlen, veraltet, falsch oder durch upstream Rate-Limits zeitweise nicht verfügbar sein. In diesen Fällen werden Lookupfehler nicht gespeichert und kein Bestand verändert; der Nutzer kann begrenzt erneut versuchen oder manuell fortfahren. Automatisierte Tests verwenden ausschließlich Provider-Mocks. Ein Live-Open-Facts-Test wurde in dieser Entwicklungsrunde **nicht durchgeführt**.

## Noch offene Hardware-/Supervisor-Checks

- iPhone-Kamera und iOS-/Ingress-/Nabu-Casa-Verhalten: manuell nach obiger Liste offen; automatisierte ZXing-Tests verwenden Kamera-Mocks.
- Home Assistant OS auf Raspberry Pi 4 `rpi4-64` / `aarch64`: ARM64 Docker-Build und Smoke-Test sind nur ein CI-Nachweis, kein Supervisor- oder Pi-Test.
- Supervisor-Backup/Restore beim Wechsel zwischen Repository-URLs/Branches mit unterschiedlicher App-ID: nicht auf Hardware ausgeführt. Vollständiges HA-Backup vor einem Upgrade erstellen; Branch-Wechsel kann ein separates `/data`-Verzeichnis bedeuten.
- PWA, Offline-Betrieb der App und eigenständiger Homescreen-Zugang: nicht implementiert. Produktsuche funktioniert offline nicht, aber manuelle Artikelerfassung bleibt verfügbar.
- Produktions-Home-Assistant und Raspberry Pi: nicht verändert; es wurde keine Installation vorgenommen.
