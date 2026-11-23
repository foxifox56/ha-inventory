# Geplante HA Inventory Integration

Dieses Verzeichnis dokumentiert den vorgesehenen Platz und Vertrag für eine eigenständige Home-Assistant-Integration. In Version 0.2 liegt hier bewusst noch keine installierbare Integration mit `manifest.json` oder `config_flow.py`.

Die spätere Komponente verwendet ausschließlich die versionierte REST-API aus [`docs/API.md`](../../docs/API.md). Sie greift nicht direkt auf SQLite zu und schreibt niemals automatisch Bestand, wenn ein Barcode gescannt oder ein Einkaufslistenpunkt erledigt wird.

Vor einem installierbaren Release müssen Authentifizierung und Autorisierung für einen serverseitigen HA-Client geklärt werden. Die API bleibt hinter Home Assistant Ingress; ein App-Port, ein `SUPERVISOR_TOKEN` im Browser oder eine Umgehung der HA-Anmeldung sind ausgeschlossen. Geplante Sensoren, Aktionen, Ereignisse und die idempotente To-do-/Einkaufslisten-Anbindung sind in [`docs/architecture.md`](../../docs/architecture.md) beschrieben.
