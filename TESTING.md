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
| Docker-Image-Build und Containerstart | Nicht ausführbar: Docker, Podman, Buildah, nerdctl und buildctl sind in der Entwicklungsumgebung nicht installiert |
| Echter Supervisor-Ingress- und HA OS-Test | Nicht ausgeführt: kein isolierter Home-Assistant-Host verfügbar; keine Installation auf dem produktiven Pi vorgenommen |

Die Ingress-Prüfung simuliert die erlaubte Quell-IP und testet die HTTP-Ablehnung direkter Zugriffe lokal. Sie ersetzt keinen Aufruf durch einen laufenden Home-Assistant-Supervisor. Die Neustartprüfung öffnet denselben SQLite-Datenbestand nach dem Herunterfahren und Neuerstellen des HTTP-Servers; sie ersetzt keinen Container-Neustarttest.

Die produktive Home-Assistant-Instanz und der Raspberry Pi wurden nicht verändert.
