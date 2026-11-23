# Testprotokoll

Dieses Protokoll unterscheidet automatisierte lokale Prüfungen, isolierte Container-Prüfungen und nicht ausgeführte Hardware-/Supervisor-Tests.

## Version 0.2 – lokale Prüfung

| Prüfung | Ergebnis am 23.11.2026 |
| --- | --- |
| Backend-Unit-, Migrations- und HTTP-Integrationstests | Bestanden: 22 Tests |
| Frontend-Tests mit Node.js | Bestanden: 12 Tests; Navigation, Lagerort-Filter, ZXing-Scanner-Lifecycle, Barcode-Routing und unveränderter Bestand |
| Python-Syntax (`compileall`) | Bestanden |
| JavaScript-Syntax (`node --check`) | Bestanden für Frontend-App, Module und ZXing-Bundle |
| YAML-Parsing (`config.yaml`, `repository.yaml`) | Bestanden |
| REST API v1 | Durch HTTP-Tests geprüft: Artikel, Kategorien, Lagerorte, Bestandsstatus, Filter, Versionsheader und Schreibsitzung |
| Schreibschutz | Bestanden: GET ohne Token; POST/PATCH/DELETE mit Schreibsitzung; Mutation ohne Sitzung mit HTTP 403 abgewiesen |
| Artikel-IDs | Bestanden: unabhängig vom Barcode, bei Barcode-Änderung erhalten und nach Löschen nicht wiederverwendet |
| Bestand nach Barcode-Lookup | Bestanden: ein Scan-Lookup ändert Menge und Status nicht |
| Ingress-Grenze | Bestanden: Test lässt nur `172.30.32.2` zu und weist direkte Anfragen ab |
| Abhängigkeit ZXing | Lokal gebündelt; keine Laufzeit-CDN-Abfrage |
| Docker-Smoke-Test lokal | Nicht ausführbar: Docker-CLI ist in dieser Entwicklungsumgebung nicht installiert |
| Echte iPhone-/Safari-Kamera | Nicht getestet; Scanner-Decoder, Rückkamera-Constraint und Stop-Verhalten sind mit Node-Mocks getestet |
| Home Assistant Supervisor / Raspberry Pi 4 | Nicht getestet; es gab keine Installation auf dem produktiven Pi |
| PWA auf iOS / Nabu Casa | Nicht getestet und nicht implementiert; offene Punkte stehen in `docs/PWA-architecture.md` |

Ausgeführt aus `ha_inventory/`:

```bash
python3 -m unittest discover -s backend/tests -v
node --test frontend/tests/*.test.mjs
python3 -m compileall -q backend
node --check frontend/app.js
node --check frontend/mobile-navigation.mjs
node --check frontend/zxing-scanner.mjs
node --check frontend/vendor/zxing-browser.mjs
```

## Container-Smoke-Test

`scripts/container-smoke.sh` baut das App-Image, prüft den Start, die Ingress-Quell-IP, die versionierte API, die Schreibsitzung und `/data`-Persistenz nach Entfernen und Neuerstellen des Containers. GitHub Actions führt ihn mit Docker Buildx für `linux/amd64` und `linux/arm64` aus. Da der lokale Docker-Client fehlt, wird das Ergebnis dieses PR-Laufs ergänzt, sobald GitHub Actions abgeschlossen ist.

Der ARM64-Build prüft den Image- und Laufzeitpfad für einen Raspberry Pi 4 mit Home Assistant OS 64-bit (`rpi4-64`/`aarch64`); er ersetzt keinen echten Supervisor-/Pi-Test. Die 32-Bit-Architektur `armv7` wird nicht angeboten. Siehe die offizielle [Raspberry-Pi-Installationsanleitung](https://www.home-assistant.io/installation/raspberrypi/) und die [HA-Systemarchitekturübersicht](https://www.home-assistant.io/more-info/unsupported/system_architecture/).

## Verifizierte HA-Pfade und Sicherung

Die lokale App-Installationsanleitung nennt `local_apps` in der Samba-Freigabe und `/local_apps` im Terminal; ältere `/addons`-Angaben können einen veralteten Alias oder Container-Mount bezeichnen. Siehe Home Assistant [Testing local apps](https://developers.home-assistant.io/docs/apps/testing/) und [App-Konfiguration](https://developers.home-assistant.io/docs/apps/configuration/).

`backup: cold` stoppt den Container während der Sicherung und lässt ihn danach wieder starten, sofern er zuvor lief. Die Web-Oberfläche ist währenddessen kurz nicht erreichbar. Dadurch wird SQLite zusammen mit seinen WAL-Dateien aus dem gestoppten Datenverzeichnis statt neben laufenden Schreibvorgängen gesichert.

Die API und Web-Oberfläche bleiben auf Home Assistant Ingress begrenzt. Kein zusätzlicher Host-Port wurde eingerichtet. Weder die produktive Home-Assistant-Instanz noch der Raspberry Pi wurden verändert; die Änderungen werden separat zur Review vorgelegt und nicht automatisch nach `main` übernommen.
