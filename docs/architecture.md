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

## Produkterkennung und Provider

```text
Frontend → Ingress/API → ProductLookupService → Open Facts
                 └────→ InventoryService → SQLite
```

`GET /api/v1/product-lookup/{barcode}` fragt zuerst `InventoryService` und SQLite ab. Das gilt für alle gültigen gespeicherten Artikelcodes bis 64 Zeichen, einschließlich alphanumerischer Codes wie `TOOL-001`. Nur ein lokaler Nichttreffer mit einem rein numerischen Code wird an Open Facts weitergereicht. Ein unbekannter alphanumerischer Code geht direkt in die manuelle Erfassung. Version 0.2 registriert den `OpenFactsProvider`, der die offizielle universelle API mit `product_type=all` nutzt. Sie liefert Treffer aus Open Food Facts, Open Beauty Facts, Open Pet Food Facts oder Open Products Facts samt Produktart. Künftige Provider für Elektronik, Werkzeuge oder Ersatzteile implementieren dasselbe kleine `lookup(barcode)`-Verhalten; Handler und Frontend bleiben providerunabhängig.

Der Provider verwendet HTTPS, einen fünfsekündigen Timeout und einen identifizierenden `HA-Inventory/0.2` User-Agent. Er folgt höchstens vier Weiterleitungen ausschließlich zwischen den offiziellen `world.*.open*facts.org` API-Hosts, liest maximal 512 KiB JSON und erlaubt Produktbilder nur über HTTPS-Hosts aus dem Open-Facts-Ökosystem. Ungecachte externe Anfragen starten pro Prozess höchstens alle 4,1 Sekunden. Ein früherer Folgeabruf erhält sofort `429` mit `retry_after_seconds`; der Backend-Worker wartet nicht und wird nicht blockiert. Der Browser zeigt den Wartezustand, versucht maximal zweimal innerhalb von höchstens zwölf Sekunden erneut und kann den Wartevorgang zugunsten der manuellen Erfassung abbrechen. Bei Anbieterfehlern oder zu langen Rate-Limits bleiben „Erneut versuchen“ und „Manuell erfassen“ verfügbar. Ein begrenzter In-Memory-LRU-Cache hält bis zu 256 Treffer sechs Stunden und Nichttreffer fünf Minuten; Fehler und Timeouts werden nicht gecacht. Damit bleibt die lokale Lagerverwaltung nutzbar, wenn Open Facts ausfällt.

Ein externer Treffer ist ausschließlich ein nicht persistierter Formvorschlag. Er enthält Barcode, Name, Marke, Packungsgröße, Kategorie, Bildadresse und Bildlizenz sowie Quelle und Produktseite. Der Nutzer kann alle Produktfelder bearbeiten. Erst die separate API-Mutation nach ausdrücklichem Speichern legt den Artikel an; der neue Datensatz beginnt im vorhandenen Standardmodell `simple` / `unknown` / `quantity=null`, sofern der Nutzer nicht im Formular etwas anderes auswählt. Weder Kamera- noch manuelle Suche ändert Bestand oder Lagerorte.

Nur der Barcode wird an Open Facts gesendet; Artikelname, Lagerort, Menge und andere Inventardaten bleiben lokal. Open Facts dokumentiert freiwillige nutzergenerierte Daten ohne Genauigkeitsgarantie, ODbL für die Datenbank, Database Contents License für einzelne Inhalte und CC BY-SA für Produktbilder. Der Client zeigt eine Quellenverknüpfung und den providerseitig gelieferten Bild-Lizenzhinweis. Für gespeicherte Vorschläge bleiben `data_source`, `source_url` und `image_license` als Attributionsmetadaten erhalten. Quell-URLs müssen HTTPS nutzen; Bild-URLs müssen zusätzlich von für den Provider freigegebenen Hosts stammen. Vor einer Veröffentlichung, einem Export oder einem anderen Nutzungsszenario müssen die aktuellen Open-Facts-Bedingungen geprüft werden. Quellen: [API-Dokumentation](https://openfoodfacts.github.io/openfoodfacts-server/api/) und [universelle Barcode-Suche über die Facts-Projekte](https://openfoodfacts.github.io/openfoodfacts-server/api/tutorials/scanning-cosmetics-pet-food-and-other-products/).

Die zusätzliche Artikeltabelle-Migration v4 fügt nur optionale Produktmetadaten-Spalten mit leeren Standardwerten hinzu. Bestehende IDs, Barcodes, Kategorien, Notizen, Lagerorte, Bestandsmodell und bestätigte Mengen bleiben erhalten. Die Integration bleibt SQLite-exklusiv; andere Apps greifen weiter über die dokumentierte Ingress-API zu.

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
