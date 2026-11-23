# HA Inventory

Eine lokale, universelle Lagerverwaltung als Home-Assistant-App. Version 0.1 bietet Artikelsuche, Barcode-Zuordnung, Kategorien, Lagerorte und einen manuell gepflegten Bestand.

**Scannen verändert den Bestand nicht.** Ein bereits bekannter Barcode öffnet den vorhandenen Artikel; ein unbekannter Barcode startet die Erfassung. Mengen werden nur geändert, wenn du sie im Artikel ausdrücklich anpasst und speicherst.

## Funktionen in Version 0.1

- Artikel für Lebensmittel, Werkzeuge, Haushaltsartikel und weitere Kategorien erfassen
- Artikel über Namen oder Barcode suchen
- Experimenteller Kamera-Scan in Browsern mit `BarcodeDetector`; iPhone/Safari ist nicht verlässlich unterstützt
- Manuelle Eingabe oder USB-/Bluetooth-Scanner als verlässlicher Fallback
- Drei Bestandsmodelle: einfacher Vorrat, geschätztes Inventar und manuell gezählter exakter Bestand
- Unbekannte Mengen bleiben ausdrücklich unbekannt; ein Scan setzt keine Stückzahl
- Niedrige Bestände und Kategorien in der Übersicht erkennen
- Änderungen lokal in SQLite speichern; keine Cloud und kein bPlaced-Konto erforderlich
- Home-Assistant-Oberfläche über Ingress öffnen

## Installation auf Home Assistant OS

Die App-Struktur ist für Home Assistant OS auf einem Raspberry Pi 4 vorbereitet. Der Home-Assistant-Supervisor baut das Image aus der `Dockerfile` auf dem Gerät; der erste Build kann einige Minuten dauern. Die Datenbank liegt dauerhaft im App-Datenverzeichnis und wird vom Home-Assistant-Backup erfasst.

**Wichtig:** Das GitHub-Repository ist derzeit privat. Home Assistant kann es nicht einfach über die normale Repository-URL aus dem App Store beziehen. Für einen Test nach der Überprüfung muss der App-Ordner lokal bereitgestellt werden. Ich habe die App nicht auf deinem produktiven Home Assistant installiert.

### Lokaler Test nach der Überprüfung

1. Kopiere den Inhalt von `ha_inventory/` in den `local_apps/ha_inventory/`-Ordner von Home Assistant OS.
2. Öffne **Einstellungen → Apps → App installieren** und aktualisiere die App-Liste.
3. Wähle unter **Local apps** die **HA Inventory** aus und installiere sie.
4. Starte die App und öffne die Web-Oberfläche.

Der `local_apps`-Ordner ist der Home-Assistant-Entwicklungsweg für lokal bereitgestellte Apps. Die aktuelle Branch kannst du in GitHub als ZIP herunterladen; kopiere dann nur den Inhalt des darin enthaltenen `ha_inventory/`-Ordners. Du erreichst `local_apps` beispielsweise über eine bereits installierte Samba-Share- oder Terminal-&-SSH-App. Diese Schritte verändern den Home Assistant; führe sie erst aus, wenn du die Version geprüft hast und einen Test dort möchtest.

Der App-Eintrag unterstützt Home Assistant OS auf Raspberry Pi 4 (`aarch64`) sowie `amd64`-Builds. `armv7` wurde entfernt, da Home Assistant diese Architektur als veraltet kennzeichnet. Für automatische Updates aus dem App Store müsste später ein öffentlich erreichbares Repository oder ein anderer für den Supervisor erreichbarer Git-Endpunkt eingerichtet werden.

### Barcode-Scan mit der Handykamera

Der Kamera-Scan in 0.1 ist ein experimenteller Vorschauweg: Er benötigt `BarcodeDetector` und einen sicheren Web-Kontext. iPhone/Safari unterstützt diese Browser-API nicht verlässlich und wurde nicht als funktionsfähiges Scan-Gerät freigegeben. Gib Codes im Scan-Dialog ein oder verwende einen Bluetooth-/USB-Scanner, der den Code wie Tastatureingaben sendet. Ein iOS-tauglicher Kamera-Decoder ist für eine spätere Version vorgesehen.

## Lokal starten

Voraussetzung: Python 3.12 oder neuer. Es gibt keine externen Python-Pakete.

```bash
cd ha_inventory
INVENTORY_DATA_DIR=../.local-data INVENTORY_ALLOW_DIRECT_ACCESS=1 python3 -m backend
```

Danach im Browser `http://127.0.0.1:8099` öffnen. `INVENTORY_ALLOW_DIRECT_ACCESS=1` ist ausschließlich für lokale Entwicklung gedacht. Die Home-Assistant-App akzeptiert standardmäßig nur Anfragen über den Ingress-Proxy.

## Tests

```bash
cd ha_inventory
python3 -m unittest discover -s backend/tests -v
node --test frontend/tests/*.test.mjs
```

Ein vollständiger Container-Build-/Starttest mit Ingress-Quell-IP und
Persistenz nach Container-Neustart läuft in GitHub Actions für diesen Pull
Request. Lokal kannst du ihn mit installiertem Docker aus dem Repository-Root
ausführen:

```bash
bash scripts/container-smoke.sh
```

Siehe [TESTING.md](TESTING.md) für die zuletzt ausgeführten Prüfungen.

## Projektstruktur

```text
AGENTS.md                  Architektur- und Entwicklungsregeln
repository.yaml            Home-Assistant-App-Repository-Metadaten
ha_inventory/
  config.yaml              Home-Assistant-App-Konfiguration
  Dockerfile               Multi-Architektur-Image für HA OS
  backend/
    inventory/             Bestandsregeln und Repository
    web/                   HTTP API und statische Auslieferung
    tests/                 Unit- und HTTP-Integrationstests
  frontend/                Responsive Web-Oberfläche
```

## Datenmodell

Ein Artikel enthält Name, optional eindeutigen Barcode, Kategorie, Lagerort, Mindestmenge, Notiz und Zeitstempel. Das Bestandsmodell lautet `simple`, `inventory` oder `exact`; `stock_status` hält fest, ob der Bestand unbekannt, vorhanden, nicht vorhanden oder als Menge erfasst ist. `quantity` ist nullable. Im einfachen Vorratsmodus wird nur Vorhandensein verwaltet, Inventar zeigt eine geschätzte Menge und exakter Bestand einen manuell eingetragenen Zählstand. Der Barcode wird als Text gespeichert, damit führende Nullen erhalten bleiben. Änderungen werden nie aus Scan-Vorgängen abgeleitet.

## Grenzen von Version 0.1

- Produktnamen werden nicht automatisch aus einem Online-Katalog geladen; ein unbekannter Artikel wird einmal manuell benannt.
- Mengenverbrauch wird nicht automatisch erfasst.
- Es gibt noch keine Home-Assistant-Entitäten, Benachrichtigungen, Mehrbenutzerrechte oder bPlaced-Anbindung.
- Die Datenbank bleibt vollständig lokal in der App.

## Entwicklung

Die Anwendung wird auf `development/v0.1` entwickelt und zur Überprüfung als Pull Request angeboten. `main` enthält derzeit nur den Repository-Startpunkt.
