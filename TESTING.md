# Testprotokoll

Dieses Protokoll wird nach den Prüfungen für den jeweiligen Entwicklungsstand aktualisiert.

## Version 0.1 — Review-Korrekturen

| Prüfung | Ergebnis |
| --- | --- |
| Python-Unit-, Migrations- und HTTP-Integrationstests | Bestanden: 19 Tests |
| Frontend-Tests mit `node --test` | Bestanden: 6 Tests |
| Python-Syntaxprüfung (`compileall`) | Bestanden |
| JavaScript-Syntaxprüfung (`node --check`) | Bestanden |
| YAML-Dateien (`repository.yaml`, `ha_inventory/config.yaml`) | Bestanden |
| SQLite nach HTTP-Server-Neustart | Bestanden: angelegte Menge und Status bleiben erhalten |
| Ingress-Proxy-Regel | Bestanden: Proxy-IP erlaubt, direkte LAN-Anfrage abgewiesen |
| GitHub Actions: Backend-/Frontend-Tests und Syntaxprüfungen | Bestanden: [Workflow-Lauf #1](https://github.com/foxifox56/ha-inventory/actions/runs/45166901759) |
| Isolierter Docker-Build, Containerstart, Ingress-HTTP und `/data` nach Container-Neustart | Bestanden: [Workflow-Lauf #1](https://github.com/foxifox56/ha-inventory/actions/runs/45166901759) |
| Docker-CLI in der lokalen Entwicklungsumgebung | Nicht verfügbar: Docker und alternative Container-Builder sind dort nicht installiert |
| Echter Supervisor-Ingress- und HA OS-Test | Nicht ausgeführt: kein isolierter Home-Assistant-Host verfügbar; keine Installation auf dem produktiven Pi vorgenommen |

Der Docker-Smoke-Test lief am 23.11.2026 auf einem isolierten GitHub Actions Runner. Er weist den Test-Client der erlaubten Proxy-IP `172.30.32.2` zu, prüft damit HTTP/API-Zugriff, weist eine andere Quell-IP ab und liest denselben Artikel nach Entfernen und Neuerstellen des App-Containers aus dem gemounteten `/data`-Verzeichnis aus. Das prüft die Container- und Ingress-Regeln, ersetzt aber keinen Aufruf durch einen laufenden Home-Assistant-Supervisor. Zusätzlich bestätigt der lokale HTTP-Test die SQLite-Daten nach einem Server-Neustart.

`scripts/container-smoke.sh` kann mit Docker auch lokal gestartet werden. `.github/workflows/ci.yml` führt ihn zusammen mit den automatisierten Tests für den Pull Request aus.

Die produktive Home-Assistant-Instanz und der Raspberry Pi wurden nicht verändert.
