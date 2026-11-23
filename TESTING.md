# Testprotokoll

Dieses Protokoll hält die lokalen Prüfungen sowie die isolierten GitHub-Actions-Läufe fest.

## Version 0.1 — zweite Review-Korrektur

| Prüfung | Ergebnis |
| --- | --- |
| Python-Unit-, Migrations- und HTTP-Integrationstests | Bestanden: 19 Tests |
| Frontend-Tests mit `node --test` | Bestanden: 7 Tests, einschließlich Wechsel von numerischem Bestand zu einfachem Vorrat |
| Python-Syntaxprüfung (`compileall`) | Bestanden |
| JavaScript-Syntaxprüfung (`node --check`) | Bestanden |
| Home-Assistant-YAML (`repository.yaml`, `ha_inventory/config.yaml`) | Bestanden; `backup: cold` und Architekturen `aarch64`/`amd64` geprüft |
| Lokaler HA-App-Installationspfad | Gegen aktuelle Entwicklerdoku geprüft: Samba-Freigabe `local_apps`, Terminalpfad `/local_apps` |
| SQLite nach HTTP-Server-Neustart | Bestanden: angelegte Menge und Status bleiben erhalten |
| Ingress-Proxy-Regel | Bestanden: Proxy-IP erlaubt, direkte LAN-Anfrage abgewiesen |
| GitHub Actions: Tests und Syntaxprüfungen | Bestanden: [Workflow-Lauf #3](https://github.com/foxifox56/ha-inventory/actions/runs/45170104746) |
| Isolierter Docker-Smoke-Test (`linux/amd64` und `linux/arm64`) | Bestanden: Build, Start, Ingress-HTTP und `/data`-Persistenz nach Container-Neustart im [Workflow-Lauf #3](https://github.com/foxifox56/ha-inventory/actions/runs/45170104746) |
| Docker-CLI in der lokalen Entwicklungsumgebung | Nicht verfügbar; der Container-Smoke-Test lief deshalb auf GitHub Actions |
| Echter Supervisor-Ingress- und HA-OS-Test | Nicht ausgeführt: kein isolierter Home-Assistant-Host verfügbar; keine Installation auf dem produktiven Pi vorgenommen |

Der Docker-Smoke-Test lief am 23.11.2026 auf einem isolierten GitHub Actions Runner für AMD64 und ARM64 (QEMU-Emulation). Er weist den Test-Client der erlaubten Proxy-IP `172.30.32.2` zu, prüft damit HTTP/API-Zugriff, weist eine andere Quell-IP ab und liest denselben Artikel nach Entfernen und Neuerstellen des App-Containers aus dem gemounteten `/data`-Verzeichnis aus. Der ARM64-Lauf prüft den für Raspberry Pi 4 erforderlichen Image- und Laufzeitpfad, ersetzt aber keinen Test auf einem tatsächlichen Pi oder Home-Assistant-Supervisor. Zusätzlich bestätigt der lokale HTTP-Test die SQLite-Daten nach einem Server-Neustart.

Die Installationsanleitung wurde mit der [offiziellen Anleitung zum Testen lokaler Apps](https://developers.home-assistant.io/docs/apps/testing/) und dem [Tutorial für die erste App](https://developers.home-assistant.io/docs/apps/first-app/) abgeglichen. Diese nennen den Ordner `local_apps` in der Samba-Freigabe und den Terminalpfad `/local_apps`. Die Home-Assistant-Konfigurationsreferenz beschreibt `addons` als veralteten Alias für den Container-Mount, nicht als aktuellen Zielordner der lokalen App.

`backup: cold` stoppt die App laut [Home-Assistant-Konfigurationsreferenz](https://developers.home-assistant.io/docs/apps/configuration/) für die Dauer der Sicherung. Die Web-Oberfläche ist dann kurz nicht verfügbar; das stoppt laufende Datenbank-Schreibvorgänge, bevor SQLite und WAL-Dateien gesichert werden.

Home Assistant OS unterstützt Raspberry Pi 4 mit der 64-Bit-Variante (`rpi4-64`/`aarch64`), nicht mit `armv7`. Diese Plattformvoraussetzung wurde mit der [offiziellen Raspberry-Pi-Installationsanleitung](https://www.home-assistant.io/installation/raspberrypi/) und der [Architekturübersicht](https://www.home-assistant.io/more-info/unsupported/system_architecture/) abgeglichen.

Die produktive Home-Assistant-Instanz und der Raspberry Pi wurden nicht verändert.
