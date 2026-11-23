# HA Inventory – Home-Assistant-App

## Installation

Füge das Repository `https://github.com/foxifox56/ha-inventory#development/v0.1` in **Einstellungen → Apps → App installieren → Repositories** hinzu. Installiere danach **HA Inventory**, starte die App und öffne die Web-Oberfläche über Ingress.

Der erste Build läuft direkt auf dem Home-Assistant-Gerät. Auf einem Raspberry Pi 4 kann das einige Minuten dauern. Es werden keine Ports auf dem Heimnetz freigegeben; die Oberfläche läuft ausschließlich über den Home-Assistant-Ingress.

## Nutzung

- Mit **Artikel anlegen** können Artikelname, Barcode, Kategorie, Bestand, Einheit, Lagerort und Mindestmenge eingetragen werden.
- Mit **Barcode scannen** wird ein bekannter Artikel gesucht. Unbekannte Codes werden in das Formular für einen neuen Artikel übernommen.
- Ein Scan verändert niemals den Bestand. Bestand und Mindestmenge werden nur durch Speichern im Artikelformular verändert.
- Ein Barcode darf nur einem Artikel zugeordnet werden. Codes werden als Zeichenfolgen gespeichert und behalten führende Nullen.
- Der Kamera-Scanner funktioniert in Browsern mit `BarcodeDetector` und verfügbarem HTTPS-Kamerazugriff. Manuelle Eingabe sowie Bluetooth-/USB-Scanner bleiben verfügbar, falls die Kamera nicht unterstützt wird.

## Speicherung und Sicherung

Die SQLite-Datenbank liegt in `/data/inventory.sqlite3`. Das Verzeichnis ist als Home-Assistant-App-Datenbereich eingebunden und Bestandteil der Supervisor-App-Sicherungen. Zum Export oder zur Wiederherstellung kann ein vollständiges Home-Assistant-Backup verwendet werden.

## Fehlerbehebung

- **Leere Liste:** Beim ersten Start ist das Lager leer. Lege einen Artikel an oder scanne einen Code.
- **Kamera nicht verfügbar:** Öffne Home Assistant über HTTPS, erlaube den Kamerazugriff oder verwende die manuelle Codeeingabe.
- **App startet nicht:** Prüfe die App-Protokolle im Home-Assistant-App-Menü. Der erste Container-Build kann auf dem Pi länger dauern.
- **Daten behalten:** Die App nicht deinstallieren, wenn die Daten erhalten bleiben sollen. Vor Änderungen ein Home-Assistant-Backup erstellen.

## Sicherheit

Der HTTP-Server akzeptiert standardmäßig nur Anfragen von Home Assistant Ingress (`172.30.32.2`). Das App-Verzeichnis benötigt weder Host-Netzwerk noch privilegierte Rechte, Home-Assistant-API-Zugang oder Zugriff auf die Konfigurationsdateien.
