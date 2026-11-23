# Architektur und Integrationsgrenzen

## Datenfluss

```text
iPhone / Desktop
      │ HA-authentifizierter Ingress
      ▼
  REST API v1 ─── InventoryService ─── SQLite in /data
      ▲
      │ Ingress bleibt die Zugangsschranke
Home-Assistant-Integration (später)
```

Die SQLite-Datei im Add-on-Verzeichnis `/data` ist die einzige Artikeldatenbank. Browser, Integrationen und weitere Anwendungen greifen ausschließlich über die REST-API auf Daten zu. Direkter SQLite-Zugriff, eine zusätzliche Cloud-Datenbank und ein ungeschützter Host-Port sind ausgeschlossen. Die Version-0.1-IDs bleiben durch Migrationen erhalten. Neue IDs werden durch SQLite `AUTOINCREMENT` vergeben und hängen nicht vom Barcode ab.

Die API ist der fachliche Integrationsvertrag; das Frontend ist nur ein API-Client. Artikelregeln liegen im Service, HTTP-Routing im Web-Adapter und die Home-Assistant-Verpackung im Add-on. Ein API-Versionswechsel wird über einen Pfad wie `/api/v2` eingeführt, nicht über UI-spezifische Endpunkte. Die Spezifikation steht in [API.md](API.md).

## Zugriffsschutz

- Jeder HTTP-Zugriff bleibt auf Home Assistant Ingress begrenzt. Ingress authentifiziert Home-Assistant-Nutzer und leitet nur über den Supervisor-Proxy an die App weiter.
- Lese-Endpunkte benötigen keine zusätzliche Schreibsitzung. `POST`, `PATCH` und `DELETE` verlangen zusätzlich ein kurzlebiges Schreib-Token, das nur über Ingress bezogen werden kann und nie in einer URL steht.
- Die Schreibsitzung ist Schutz gegen ungewollte Cross-Site-Anfragen. Sie ersetzt keine getrennten Home-Assistant-Rollen und ist kein externer API-Schlüssel.
- CORS ist nicht freigegeben. Ein späterer Home-Assistant-Client muss einen dokumentierten, von Home Assistant authentifizierten Weg verwenden. Kein Browser-Code bekommt `SUPERVISOR_TOKEN`, Core-Token oder Geheimnisse aus der App-Konfiguration.
- Für externe Client-Authentifizierung, Berechtigungsbereiche und Widerruf ist vor direktem API-Zugriff eine eigene Sicherheitsprüfung erforderlich. Ingress wird dabei nicht umgangen.

## Eigenständige Home-Assistant-Integration

Die spätere Integration soll als `custom_components/ha_inventory` mit eigenem Config Flow und eigenem Release-Lebenszyklus entstehen. Sie wird REST-Client der Artikel-API, kein Datenbank-Client und keine weitere Artikeldatenbank.

Vorgesehene Schnittstellen:

- Sensoren für Artikelzahl, niedrige Bestände und optionale Artikel-/Bestandswerte.
- Aktionen für ausdrücklich angeforderte Bestandsänderungen und Einkaufslisten-Vorgänge.
- Ereignisse mit Artikel-ID und Änderungstyp, beispielsweise bei einer ausdrücklich gespeicherten Änderung.

Diese Integration wird in Version 0.2 noch nicht als installierbare Home-Assistant-Komponente ausgeliefert. Die aktuelle API ist über authentifizierten Ingress nutzbar; ein sicherer serverseitiger Integrationszugang außerhalb des Browsers muss erst festgelegt und getestet werden. Siehe [custom_components/ha_inventory/README.md](../custom_components/ha_inventory/README.md).

## Einkaufslisten und To-do-Listen

Eine spätere Anbindung kann die nativen Home-Assistant-To-do-Entitäten und die Einkaufsliste über deren dokumentierte Aktionen nutzen. Sie muss als explizite Nutzeraktion starten; weder ein Scan noch das Erledigen eines Einkaufslistenpunkts ändert automatisch den Lagerbestand.

Vor dem Hinzufügen prüft die Integration auf einen bereits offenen Eintrag. Sie hält die Operation pro Artikel-ID und Zielliste idempotent, verhindert parallele Doppelklicks und speichert eine Zuordnung zwischen Artikel-ID und Listen-Eintrag, soweit die To-do-API sie bereitstellt. Wenn eine Liste nur textbasierte Aktionen anbietet, darf kein automatisches Wiederholen erfolgen, solange nicht geklärt ist, ob der erste Aufruf bereits einen Eintrag erzeugt hat. Abschluss eines Listeneintrags aktualisiert den Lagerbestand nie stillschweigend.

Die Einkaufslisten- und To-do-Integration, Sensoren, Aktionen und Ereignisse sind geplant, aber in 0.2 nicht implementiert.
