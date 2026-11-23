# HA Inventory 0.3 – Home-Assistant-App

## Installation auf Home Assistant OS

Das GitHub-Repository ist öffentlich. Der Review-Branch lässt sich im App-Store mit `https://github.com/foxifox56/ha-inventory#development/v0.3` hinzufügen (**Einstellungen → Apps → Installieren → ⋮ → Repositories**). `#branch` wählt den Branch; eine abweichende Repository-URL kann eine eigene Supervisor-App-ID und einen separaten `/data`-Speicher ergeben. Vor einem Branch- oder App-ID-Wechsel ein vollständiges HA-Backup einschließlich App-Daten erstellen. Der Backup-/Restore-Pfad zwischen verschiedenen App-IDs wurde nicht auf einem Supervisor getestet. Diesen Review-Branch nicht parallel zu einem produktiven Bestand installieren. Für lokale Entwicklung kopiere den Inhalt dieses App-Ordners in `local_apps/ha_inventory/`; im Terminal-&-SSH-Add-on ist der Pfad `/local_apps/ha_inventory/` und `config.yaml` muss direkt dort liegen. Siehe die [offizielle Anleitung für lokale Apps](https://developers.home-assistant.io/docs/apps/testing/) und [App-Repositories](https://developers.home-assistant.io/docs/apps/guides/repository/).

Ältere Beispiele mit `addons` oder `/addons` verwenden einen veralteten Alias beziehungsweise Container-Mount. Auf dem Host ist `local_apps` der aktuelle Ordner. Installiere danach unter **Einstellungen → Apps** aus **Local apps**; bei Bedarf im App-Menü **Nach Updates suchen** wählen und die Ansicht aktualisieren.

Die App unterstützt `aarch64` und `amd64`. Auf dem Raspberry Pi 4 ist Home Assistant OS 64-bit (`rpi4-64`/`aarch64`) erforderlich. Es werden keine Ports im Heimnetz freigegeben; die Web-Oberfläche läuft ausschließlich über Home-Assistant-Ingress. Diese Dokumentation wurde nicht durch eine Installation auf dem produktiven Pi geprüft.

## Nutzung

- Auf Smartphones führt die untere Navigation zu **Start**, **Suche**, **Scanner** und **Lagerorte**. Artikel erscheinen als Karten; auf größeren Bildschirmen bleibt die vollständige Bestandsansicht verfügbar.
- Das Farbschema folgt der Systemeinstellung für den Dark Mode. Bedienelemente sind für Touch vergrößert.
- Der Scanner startet in **Ansehen**: gespeicherte numerische und alphanumerische Codes öffnen Details, ohne den Bestand zu ändern. Unbekannte Codes werden zuerst lokal geprüft; nur unbekannte numerische Codes gehen an Open Facts.
- **Einlagern** verlangt eine Mengenbestätigung. **Verbrauchen** muss bewusst aktiviert werden und bucht je Scan standardmäßig eine Packung; Mehrfachmengen können vorher gewählt werden. Die Kamera stoppt nach einem Code und wird für den nächsten Scan erneut geöffnet.
- Verbrauch ist nur bei bekanntem Zahlenbestand möglich. Unbekannte Bestände müssen ausdrücklich als Startbestand initialisiert werden; ein bestätigter Startbestand `0` ist bekannt, nicht unbekannt.
- Jeder Vorgang wird dauerhaft protokolliert. Rückgängig schreibt eine einmalige Gegenbuchung; Artikel mit Buchungsverlauf können nicht gelöscht werden. Produkt-Packungsgröße ist keine Buchungs-Multiplikation.
- Erkannte Name-, Marken-, Packungsgrößen-, Kategorie- und Bilddaten erscheinen als bearbeitbare Vorschläge. Der Lookup legt keinen Artikel an; ein Produkt wird erst nach bestätigtem Speichern erfasst. Produktvorschläge buchen keinen Bestand.
- Open Facts ist freiwillig gepflegt; Angaben können fehlen oder falsch sein. Der Barcode wird per HTTPS an die gemeinsame Produkt-API gesendet. Bei zu schnellen Folgeabfragen zeigt die App einen Status und versucht höchstens zweimal erneut; die kombinierte Rate-Limit-Wartezeit ist auf 12 Sekunden begrenzt. Jede tatsächliche Anbieteranfrage hat zusätzlich ein fünfsekündiges Timeout. Der Wartevorgang ist abbrechbar; bei Offline-/Timeout-/Rate-Limit-Fehlern gibt es die Optionen „Erneut versuchen“ und „Manuell erfassen“. Datenquelle und Bildlizenz werden in der Oberfläche angezeigt.
- ZXing öffnet die rückwärtige Kamera, sofern der Browser einen sicheren Kontext, Kamerazugriff und die nötigen Browserfunktionen bereitstellt. iOS/Safari wurde hier nicht auf echter Hardware getestet. Bei Problemen kannst du einen Code manuell eingeben oder einen Bluetooth-/USB-Scanner wie eine Tastatur verwenden.
- Artikel haben eine von ihrem optionalen Barcode unabhängige SQLite-ID. Kategorien und Lagerorte sind frei benennbar und werden als Werte aus Artikeln abgeleitet.
- Das Bestandsmodell `simple` hält unbekannt/vorhanden/nicht vorhanden fest; `inventory` verwaltet Schätzmengen; `exact` verwaltet manuell gezählte Mengen. Eine leere Menge bedeutet unbekannt, eine erfasste `0` bedeutet Nullbestand.

## REST API und Sicherheit

Neue API-Clients verwenden `/api/v1`. `GET /api/v1/product-lookup/{barcode}` ist lokal-first und lesend; mögliche Ergebnisse sind `local`, `identified`, `not_found`, `rate_limited` oder `unavailable`. Siehe [REST-API-Referenz](../docs/API.md). Die Artikeldatenbank bleibt in `/data/inventory.sqlite3`; Browser und andere Anwendungen verwenden die REST-API und greifen nicht direkt auf SQLite zu.

Home Assistant Ingress authentifiziert Benutzer. Der Server nimmt nur Anfragen vom Supervisor-Proxy `172.30.32.2` an. Lesezugriffe benötigen keine zusätzliche Schreibsitzung; `POST`, `PATCH` und `DELETE` einschließlich Bewegungs- und Undo-Buchungen benötigen ein zusätzliches kurzlebiges Token aus `GET /api/v1/write-session`. Dieses Token bleibt innerhalb der Ingress-Grenze und ist kein externer API-Schlüssel. CORS und ein direkter externer API-Zugang sind nicht freigeschaltet.

Die App hat keine zusätzliche Cloud-Datenbank. Die Einkaufslisten-/To-do-Anbindung sowie die eigenständige Home-Assistant-Integration mit Sensoren, Aktionen und Ereignissen sind als nächste Architekturarbeit geplant. Vor deren Umsetzung muss ein sicherer HA-authentifizierter Zugang zur API geprüft werden; Details stehen in [architecture.md](../docs/architecture.md).

## Speicherung und Sicherung

Die Datenbank liegt in `/data/inventory.sqlite3`. Home Assistant stellt `/data` als persistenten App-Speicher bereit. `backup: cold` stoppt den Container für die Sicherung und startet ihn danach wieder, sofern er zuvor lief. Währenddessen ist die Web-Oberfläche kurz nicht erreichbar. SQLite und WAL-Dateien werden aus dem gestoppten App-Datenverzeichnis gesichert, nicht parallel zu laufenden Schreibvorgängen.

Schema-Upgrades behalten Artikelmetadaten und vorhandene IDs bei. Migration v4 ergänzt Produktmetadaten; v5 legt die Buchungstabelle und einen Index an. v6 baut nur das Bewegungsjournal um und übernimmt IDs, Schlüssel und Undo-Referenzen, damit ein ausdrücklich bestätigter Nullbestand als Bewegung protokolliert werden kann. Artikelzeilen und -bestände bleiben unangetastet. Die frühe v0.1-Version verwendete eine automatische Menge `1`; deren alte Werte wurden zu „unbekannt“ migriert, weil sie nicht sicher von manuell erfassten Mengen unterschieden werden können.

## Fehlerbehebung

- **Kamera nicht verfügbar:** Prüfe HTTPS, die Kameraberechtigung und den Browser. Verwende alternativ manuelle Eingabe oder einen Tastatur-Scanner.
- **Artikelliste leer:** Beim ersten Start ist das Lager leer. Lege einen Artikel an oder suche/scanne einen Barcode.
- **Schreibzugriff abgelehnt:** Öffne die Oberfläche erneut über Home-Assistant-Ingress. Schreibsitzungen laufen nach einer Stunde ab und werden nicht in URLs abgelegt.
- **Produktsuche findet nichts oder ist offline:** Unbekannte alphanumerische Codes gehen direkt in die manuelle Erfassung. Bei unbekannten numerischen Codes bleiben bei einem Treffer Vorschläge editierbar; bei Ausfall stehen „Erneut versuchen“ und „Manuell erfassen“ bereit. Ein Rate-Limit wartet nur begrenzt im Browser und blockiert keinen Backend-Worker.
- **App startet nicht:** Prüfe die App-Protokolle. Der erste Container-Build auf dem Gerät kann länger dauern.
- **Daten behalten:** Deinstalliere die App nicht, wenn die Daten erhalten bleiben sollen. Erstelle vor Änderungen ein Home-Assistant-Backup.
