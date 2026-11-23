# Testprotokoll

Stand: 23.11.2026 · Branch `development/v0.3`. Automatisierte Tests verwenden temporäre SQLite-Datenbanken sowie gemockte Provider-Antworten. Es werden keine Live-Produktdaten bei Open Facts angefragt.

## Automatisierte Prüfungen

| Prüfung | Umfang und Ergebnis |
| --- | --- |
| Backendtests | 54 Tests bestanden: v1-API, Ingress und Schreibsitzung, Produkt-Lookup, Bewegungsservice, Idempotenz, parallele Scans, negativer Bestand, Startbestand, Undo und Fehlerbehandlung |
| Frontendtests | 30 Tests bestanden: Produkt-Lookup, Bestandsschutz, Scan-Modi, Mengenrouting, kurze Doppelscan-Sperre, Idempotenzschlüssel, Buchungspayloads und Kameraadapter |
| Rückwärtskompatibilität | v1-/v3-Altstände und der v4→v5-Upgradepfad; IDs, Barcodes, Metadaten und Mengen bleiben erhalten |
| Syntax | `compileall` und `node --check` für App, API-Client, Produkt-Lookup, Scanner, Navigations- und Buchungsmodule bestanden |
| Home-Assistant-App-Konfiguration | YAML erfolgreich gelesen; Version `0.3.0`, Architekturen `aarch64`/`amd64`, `backup: cold` |
| Docker lokal | Nicht ausgeführt: Docker-CLI ist in der Entwicklungsumgebung nicht verfügbar |
| Docker-Smoke-Test in GitHub Actions | In den erfolgreichen Runs #23 und #24 für `linux/amd64` und `linux/arm64`; Buchung, idempotentes Replay, Undo und Verlauf nach Neustart geprüft |
| GitHub Actions Push-Workflow | [Run #23](https://github.com/foxifox56/ha-inventory/actions/runs/45221539257) erfolgreich: Tests sowie AMD64- und ARM64-Container-Smoke bestanden |
| GitHub Actions PR-Workflow | [Run #24](https://github.com/foxifox56/ha-inventory/actions/runs/45221614596) erfolgreich: Tests sowie AMD64- und ARM64-Container-Smoke bestanden |

Befehle aus `ha_inventory/`:

```bash
python3 -m unittest discover -s backend/tests -v
node --test frontend/tests/*.test.mjs
python3 -m compileall -q backend
for file in frontend/*.js frontend/*.mjs frontend/vendor/*.mjs; do node --check "$file" || exit 1; done
```

GitHub Actions führte die Backend- und Frontendtests sowie den Container-Smoke-Test für `linux/amd64` und `linux/arm64` für den Implementierungsstand `2725791` aus. Beide genannten Läufe waren erfolgreich. Ein ARM64-Container-Test ist kein Supervisor- oder Raspberry-Pi-Hardwaretest; die Läufe belegen keinen echten Pi-/Supervisor-Test.

## Manuelle Testanleitung: iPhone über Ingress und Nabu Casa

Der echte iPhone-Kameratest wurde in dieser Entwicklungsrunde **nicht durchgeführt**. Hierfür ist ein separates Home-Assistant-Testsystem mit Ingress-Zugriff und ein iPhone erforderlich. Keine Add-on-IP, keinen Port und keine direkte App-URL öffnen.

1. Auf dem iPhone in Home Assistant anmelden. Im Heim-WLAN die eigene HTTPS-Adresse von Home Assistant, außerhalb des Hauses die Nabu-Casa-Remote-URL verwenden. HA Inventory über **Einstellungen → Apps → HA Inventory → Öffnen** starten, damit HA-Anmeldung und Ingress erhalten bleiben.
2. Scanner öffnen. Prüfen, dass **Ansehen** vorausgewählt ist. Einen gespeicherten numerischen Barcode und einen alphanumerischen Code scannen. Derselbe Artikel muss erscheinen; Menge, Status und Lagerort müssen unverändert bleiben.
3. Einen unbekannten numerischen Barcode scannen. Produktvorschläge prüfen, Felder ändern und abbrechen: Es darf kein Artikel entstehen. Bei nicht verfügbarem Open Facts müssen Fehlermeldung, erneuter Versuch und manuelle Alternative funktionieren.
4. Einen unbekannten alphanumerischen Code scannen. Er muss ohne externen Produktaufruf im vorausgefüllten manuellen Formular erscheinen. Abbrechen darf nichts speichern.
5. Für einen vorhandenen Artikel **Einlagern** wählen, 1 und danach mehrere Packungen testen. Die Kamera öffnet nach einem Treffer nicht erneut automatisch. Vor Bestätigung darf sich der Bestand nicht ändern; nach Bestätigung muss genau die gewählte ganze Packungszahl hinzukommen.
6. Für einen Artikel mit unbekanntem/einfachem Bestand **Einlagern** testen. Ohne Bestätigung des Startbestands muss die Buchung scheitern. Mit Bestätigung und gewähltem Bestandsmodell muss ein Verlaufseintrag entstehen.
7. **Verbrauchen** ausdrücklich aktivieren. Ohne Mengenänderung muss ein Scan eine Packung abziehen; mit gewählter Mehrfachmenge muss genau diese Zahl abgehen. Eine Abbuchung über den Bestand hinaus wird abgelehnt und darf die Daten nicht ändern.
8. Nach Einlagerung und Verbrauch **Rückgängig** verwenden. Der Verlauf muss Original und Gegenbuchung zeigen; wiederholtes Undo muss abgelehnt werden. Wiederholtes Kamerabild vor erneutem Öffnen darf keine Doppelbuchung auslösen.
9. Eine abgelaufene Schreibsitzung über eine normale Buchung prüfen. Die App muss die Schreibsitzung einmal erneuern; Ingress-Fehler dürfen nicht als Tokenablauf wiederholt werden.
10. App neu starten und Artikel sowie Buchungsverlauf kontrollieren. Der Bestand muss erhalten bleiben.

## Grenzen und nicht durchgeführte Prüfungen

- Live-Abfragen bei Open Facts: **nicht durchgeführt**. Provider-Verhalten wurde mit Mocks getestet; echte Rate-Limits, Netzwerkausfälle und Datenqualität hängen vom Anbieter ab.
- iPhone-Kamera, Safari/In-App-Browser, Home-Assistant-Ingress und Nabu Casa: **nicht durchgeführt**.
- Installation, Supervisor-Upgrade/Backup und Raspberry Pi 4 mit HAOS 64-bit: **nicht durchgeführt**. Es wurden keine Änderungen am produktiven Home Assistant oder Raspberry Pi vorgenommen.
- Lokaler Docker-Smoke-Test: **nicht durchgeführt**, weil Docker hier fehlt. Die erfolgreichen AMD64-/ARM64-GitHub-Actions-Ergebnisse sind oben verlinkt.
- Bewegungen zählen positive ganze Packungen. Produktgrößen wie `1 l` sind keine Mengenumrechnung. Unbekannte Bestände müssen zuerst ausdrücklich initialisiert werden. Beleg-OCR, Offline-PWA und direkte externe API-Zugänge sind nicht Teil von v0.3.
