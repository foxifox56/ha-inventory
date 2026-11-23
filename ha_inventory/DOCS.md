# HA Inventory – Home-Assistant-App

## Installation auf Home Assistant OS

Das GitHub-Repository ist derzeit privat und kann nicht über die normale Repository-URL im App Store bezogen werden. Für einen lokalen Test nach der Überprüfung kopiere den Inhalt dieses App-Ordners in `local_apps/ha_inventory/` in der Samba-Freigabe von Home Assistant OS. Über Terminal & SSH ist das `/local_apps/ha_inventory/`; danach muss `config.yaml` direkt in diesem Ordner liegen. Die aktuelle [Home-Assistant-Anleitung für lokale Apps](https://developers.home-assistant.io/docs/apps/testing/) beschreibt diesen `local_apps`-Pfad.

`/addons` kann in älteren Konfigurationen als veralteter Alias bzw. als Container-Mount für `local_apps` auftauchen. Für die lokale Bereitstellung auf dem Host ist der aktuelle Ordner `local_apps` beziehungsweise `/local_apps`.

Installiere anschließend unter **Einstellungen → Apps** aus dem Bereich **Local apps**. Falls die App noch nicht erscheint, wähle im App-Menü **Nach Updates suchen** und aktualisiere die Ansicht.

Der lokale App-Ordner ist für die Entwicklung vorgesehen. Lade dazu die geprüfte Branch als ZIP herunter und kopiere den Inhalt des darin enthaltenen `ha_inventory/`-Ordners hierhin. Der Supervisor baut das Image beim Installieren direkt auf dem Home-Assistant-Gerät; auf einem Raspberry Pi 4 kann das einige Minuten dauern. Für Raspberry Pi 4 muss Home Assistant OS als 64-Bit-Variante (`rpi4-64`, Architektur `aarch64`) laufen. Der App-Eintrag unterstützt `aarch64` und `amd64`; der ARM64-Container-Build wird in GitHub Actions geprüft. Es werden keine Ports im Heimnetz freigegeben; die Oberfläche läuft ausschließlich über Home-Assistant-Ingress.

Diese Schritte verändern Home Assistant. Die App wurde in der Entwicklungsrunde nicht auf einer Home-Assistant-Instanz installiert.

## Nutzung

- Mit **Artikel anlegen** können Artikelname, Barcode, Kategorie, Lagerort und das passende Bestandsmodell gewählt werden.
- Die Bestandsmodelle sind **Einfacher Vorrat** (unbekannt/vorhanden/nicht vorhanden), **Inventar** (manuell geschätzte Menge) und **Exakter Bestand** (manuell gezählte Menge).
- Eine leere Menge bedeutet ausdrücklich **Bestand unbekannt**. Eine eingetragene 0 ist ein bekannter Nullbestand.
- Ein bekannter Barcode öffnet eine Detailansicht mit Name, Kategorie, Lagerort und Bestandsstatus. Unbekannte Codes werden in das Formular für einen neuen Artikel übernommen.
- Ein Scan verändert niemals den Bestand. Bestand und Mindestmenge werden nur durch Speichern im Artikelformular verändert.
- Ein Barcode darf nur einem Artikel zugeordnet werden. Codes werden als Zeichenfolgen gespeichert und behalten führende Nullen.
- Der Kamera-Scan in 0.1 ist experimentell: Er nutzt die Browser-API `BarcodeDetector`, ist auf iPhone/Safari nicht verlässlich und wurde dort nicht getestet. Manuelle Eingabe sowie Bluetooth-/USB-Scanner funktionieren als Fallback.

## Speicherung und Sicherung

Die SQLite-Datenbank liegt in `/data/inventory.sqlite3`. Home Assistant stellt `/data` standardmäßig als privaten, dauerhaften App-Speicher bereit und nimmt es in App-Backups auf. In `config.yaml` ist `backup: cold` gesetzt: Der Supervisor stoppt den App-Container während der Sicherung und startet ihn danach wieder, sofern er zuvor lief. Währenddessen ist die Web-Oberfläche kurz nicht verfügbar. SQLite und die zugehörigen WAL-Dateien werden aus dem gestoppten App-Datenverzeichnis gesichert, statt parallel zu laufenden Schreibvorgängen kopiert zu werden. Zum Export oder zur Wiederherstellung kann ein vollständiges Home-Assistant-Backup verwendet werden.

Beim Schema-Upgrade von der ersten 0.1-Version bleiben Artikeldaten wie Barcode, Kategorie, Lagerort und Notiz erhalten. Alte Mengen werden auf „unbekannt“ zurückgesetzt, weil Version 1 automatisch `1` eingetragen hat und sich diese Standardwerte nicht sicher von bewusst eingegebenen Mengen unterscheiden lassen. Verifizierte Mengen können danach manuell neu eingetragen werden.

## Fehlerbehebung

- **Leere Liste:** Beim ersten Start ist das Lager leer. Lege einen Artikel an oder scanne einen Code.
- **Kamera nicht verfügbar:** Der Kamera-Scan ist in 0.1 nur experimentell. Verwende die manuelle Codeeingabe oder einen Bluetooth-/USB-Scanner.
- **App startet nicht:** Prüfe die App-Protokolle im Home-Assistant-App-Menü. Der erste Container-Build kann auf dem Pi länger dauern.
- **Daten behalten:** Die App nicht deinstallieren, wenn die Daten erhalten bleiben sollen. Vor Änderungen ein Home-Assistant-Backup erstellen.

## Sicherheit

Der HTTP-Server akzeptiert standardmäßig nur Anfragen von Home Assistant Ingress (`172.30.32.2`). Das App-Verzeichnis benötigt weder Host-Netzwerk noch privilegierte Rechte, Home-Assistant-API-Zugang oder Zugriff auf die Konfigurationsdateien.
