# HA Inventory 0.2 – Home-Assistant-App

## Installation auf Home Assistant OS

Das GitHub-Repository ist privat und kann nicht über die normale Repository-URL aus dem App Store bezogen werden. Für einen späteren lokalen Test kopiere den Inhalt dieses App-Ordners in `local_apps/ha_inventory/` in der Samba-Freigabe von Home Assistant OS. Im Terminal-&-SSH-Add-on ist der Pfad `/local_apps/ha_inventory/`; `config.yaml` muss direkt in diesem Ordner liegen. Siehe die [offizielle Anleitung für lokale Apps](https://developers.home-assistant.io/docs/apps/testing/).

Ältere Beispiele mit `addons` oder `/addons` verwenden einen veralteten Alias beziehungsweise Container-Mount. Auf dem Host ist `local_apps` der aktuelle Ordner. Installiere danach unter **Einstellungen → Apps** aus **Local apps**; bei Bedarf im App-Menü **Nach Updates suchen** wählen und die Ansicht aktualisieren.

Die App unterstützt `aarch64` und `amd64`. Auf dem Raspberry Pi 4 ist Home Assistant OS 64-bit (`rpi4-64`/`aarch64`) erforderlich. Es werden keine Ports im Heimnetz freigegeben; die Web-Oberfläche läuft ausschließlich über Home-Assistant-Ingress. Diese Dokumentation wurde nicht durch eine Installation auf dem produktiven Pi geprüft.

## Nutzung

- Auf Smartphones führt die untere Navigation zu **Start**, **Suche**, **Scanner** und **Lagerorte**. Artikel erscheinen als Karten; auf größeren Bildschirmen bleibt die vollständige Bestandsansicht verfügbar.
- Das Farbschema folgt der Systemeinstellung für den Dark Mode. Bedienelemente sind für Touch vergrößert.
- Ein bekannter Barcode öffnet Artikeldetails, ein unbekannter Barcode startet die Erfassung. Scannen ändert nie den Bestand.
- ZXing öffnet die rückwärtige Kamera, sofern der Browser einen sicheren Kontext, Kamerazugriff und die nötigen Browserfunktionen bereitstellt. iOS/Safari wurde hier nicht auf echter Hardware getestet. Bei Problemen kannst du einen Code manuell eingeben oder einen Bluetooth-/USB-Scanner wie eine Tastatur verwenden.
- Artikel haben eine von ihrem optionalen Barcode unabhängige SQLite-ID. Kategorien und Lagerorte sind frei benennbar und werden als Werte aus Artikeln abgeleitet.
- Das Bestandsmodell `simple` hält unbekannt/vorhanden/nicht vorhanden fest; `inventory` verwaltet Schätzmengen; `exact` verwaltet manuell gezählte Mengen. Eine leere Menge bedeutet unbekannt, eine erfasste `0` bedeutet Nullbestand.

## REST API und Sicherheit

Neue API-Clients verwenden `/api/v1`. Siehe [REST-API-Referenz](../docs/API.md). Die Artikeldatenbank bleibt in `/data/inventory.sqlite3`; Browser und andere Anwendungen verwenden die REST-API und greifen nicht direkt auf SQLite zu.

Home Assistant Ingress authentifiziert Benutzer. Der Server nimmt nur Anfragen vom Supervisor-Proxy `172.30.32.2` an. Lesezugriffe benötigen keine zusätzliche Schreibsitzung; `POST`, `PATCH` und `DELETE` benötigen ein zusätzliches kurzlebiges Token aus `GET /api/v1/write-session`. Dieses Token bleibt innerhalb der Ingress-Grenze und ist kein externer API-Schlüssel. CORS und ein direkter externer API-Zugang sind nicht freigeschaltet.

Die App hat keine zusätzliche Cloud-Datenbank. Die Einkaufslisten-/To-do-Anbindung sowie die eigenständige Home-Assistant-Integration mit Sensoren, Aktionen und Ereignissen sind als nächste Architekturarbeit geplant. Vor deren Umsetzung muss ein sicherer HA-authentifizierter Zugang zur API geprüft werden; Details stehen in [architecture.md](../docs/architecture.md).

## Speicherung und Sicherung

Die Datenbank liegt in `/data/inventory.sqlite3`. Home Assistant stellt `/data` als persistenten App-Speicher bereit. `backup: cold` stoppt den Container für die Sicherung und startet ihn danach wieder, sofern er zuvor lief. Währenddessen ist die Web-Oberfläche kurz nicht erreichbar. SQLite und WAL-Dateien werden aus dem gestoppten App-Datenverzeichnis gesichert, nicht parallel zu laufenden Schreibvorgängen.

Schema-Upgrades behalten Artikelmetadaten und vorhandene IDs bei. Die frühe v0.1-Version verwendete eine automatische Menge `1`; deren alte Werte wurden zu „unbekannt“ migriert, weil sie nicht sicher von manuell erfassten Mengen unterschieden werden können.

## Fehlerbehebung

- **Kamera nicht verfügbar:** Prüfe HTTPS, die Kameraberechtigung und den Browser. Verwende alternativ manuelle Eingabe oder einen Tastatur-Scanner.
- **Artikelliste leer:** Beim ersten Start ist das Lager leer. Lege einen Artikel an oder suche/scanne einen Barcode.
- **Schreibzugriff abgelehnt:** Öffne die Oberfläche erneut über Home-Assistant-Ingress. Schreibsitzungen laufen nach einer Stunde ab und werden nicht in URLs abgelegt.
- **App startet nicht:** Prüfe die App-Protokolle. Der erste Container-Build auf dem Gerät kann länger dauern.
- **Daten behalten:** Deinstalliere die App nicht, wenn die Daten erhalten bleiben sollen. Erstelle vor Änderungen ein Home-Assistant-Backup.
