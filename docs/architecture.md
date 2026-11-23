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

Der Provider verwendet HTTPS, einen fünfsekündigen Timeout und einen identifizierenden `HA-Inventory/0.3` User-Agent. Er folgt höchstens vier Weiterleitungen ausschließlich zwischen den offiziellen `world.*.open*facts.org` API-Hosts, liest maximal 512 KiB JSON und erlaubt Produktbilder nur über HTTPS-Hosts aus dem Open-Facts-Ökosystem. Ungecachete externe Anfragen starten pro Prozess höchstens alle 4,1 Sekunden. Ein früherer Folgeabruf erhält sofort `429` mit `retry_after_seconds`; der Backend-Worker wartet nicht und wird nicht blockiert. Der Browser zeigt den Wartezustand, versucht maximal zweimal erneut und wartet insgesamt höchstens zwölf Sekunden auf Rate-Limit-Freigaben; jede tatsächliche Anbieteranfrage hat zusätzlich ein fünfsekündiges Timeout. Der Wartevorgang kann zugunsten der manuellen Erfassung abbrechen. Bei Anbieterfehlern oder zu langen Rate-Limits bleiben „Erneut versuchen“ und „Manuell erfassen“ verfügbar. Ein begrenzter In-Memory-LRU-Cache hält bis zu 256 Treffer sechs Stunden und Nichttreffer fünf Minuten; Fehler und Timeouts werden nicht gecacht. Damit bleibt die lokale Lagerverwaltung nutzbar, wenn Open Facts ausfällt.

Ein externer Treffer ist ausschließlich ein nicht persistierter Formvorschlag. Er enthält Barcode, Name, Marke, Packungsgröße, Kategorie, Bildadresse und Bildlizenz sowie Quelle und Produktseite. Der Nutzer kann alle Produktfelder bearbeiten. Erst die separate API-Mutation nach ausdrücklichem Speichern legt den Artikel an; im Einlagerungs-Scan wird danach zusätzlich der Startbestand explizit bestätigt. Der reine Lookup ändert nie Bestand oder Lagerorte. Der Scanner startet in `Ansehen`; Buchungen sind nur in den ausdrücklich gewählten Modi `Einlagern` oder `Verbrauchen` möglich.

Nur der Barcode wird an Open Facts gesendet; Artikelname, Lagerort, Menge und andere Inventardaten bleiben lokal. Open Facts dokumentiert freiwillige nutzergenerierte Daten ohne Genauigkeitsgarantie, ODbL für die Datenbank, Database Contents License für einzelne Inhalte und CC BY-SA für Produktbilder. Der Client zeigt eine Quellenverknüpfung und den providerseitig gelieferten Bild-Lizenzhinweis. Für gespeicherte Vorschläge bleiben `data_source`, `source_url` und `image_license` als Attributionsmetadaten erhalten. Quell-URLs müssen HTTPS nutzen; Bild-URLs müssen zusätzlich von für den Provider freigegebenen Hosts stammen. Vor einer Veröffentlichung, einem Export oder einem anderen Nutzungsszenario müssen die aktuellen Open-Facts-Bedingungen geprüft werden. Quellen: [API-Dokumentation](https://openfoodfacts.github.io/openfoodfacts-server/api/) und [universelle Barcode-Suche über die Facts-Projekte](https://openfoodfacts.github.io/openfoodfacts-server/api/tutorials/scanning-cosmetics-pet-food-and-other-products/).

Die zusätzliche Artikeltabelle-Migration v4 fügt nur optionale Produktmetadaten-Spalten mit leeren Standardwerten hinzu. Bestehende IDs, Barcodes, Kategorien, Notizen, Lagerorte, Bestandsmodell und bestätigte Mengen bleiben erhalten. Die additive Migration v5 erstellt ausschließlich `stock_movements`, Fremdschlüssel und einen Verlauf-Index; sie schreibt keine bestehenden Artikelzeilen um. Fremdschlüssel verhindern das Löschen von Artikeln mit Buchungsverlauf.

## Einlagern und Verbrauchen

```text
Scanner/UI → API /api/v1 → StockMovementService → BEGIN IMMEDIATE
                                        ├──────→ inventory_items
                                        └──────→ stock_movements
```

`StockMovementService` ist der einzige API-Anwendungsfall, der den Zahlenbestand eines bereits gespeicherten Artikels ändert. `POST /items` darf beim ausdrücklichen Anlegen einen Anfangswert als Teil des neuen Datensatzes setzen; Änderungen an bestehenden Zählständen laufen über die Bewegungs-API. Jede Bewegung aktualisiert Artikeldatensatz und unveränderlichen Verlauf gemeinsam in einer SQLite-Transaktion. `BEGIN IMMEDIATE` serialisiert konkurrierende Scans; ein eindeutiger Idempotenzschlüssel macht Wiederholungen desselben Requests sicher. Ein Schlüssel mit abweichendem Inhalt wird mit `409` abgelehnt.

Die Aktionen `receive` und `consume` verlangen einen bekannten Zahlenbestand (`inventory` oder `exact`) und eine positive ganze Packungszahl. `product_size` ist Beschreibung und ändert die gebuchte Anzahl nicht. Ein Artikel mit einfachem/unbekanntem Bestand kann nicht direkt gebucht werden. Die Aktion `initialize` verlangt eine ausdrückliche Bestätigung und setzt den Startbestand samt Bestandsmodell; auch `0` ist ein gültiger, bekannter Startbestand (`known/0`) und bleibt von unbekannt (`null`) unterscheidbar. Nur `initialize` und dessen Undo dürfen deshalb ein Ledger-Delta von `0` tragen. Ein Verbrauch unter 0 wird vor dem Commit abgelehnt.

Undo löscht keine Buchung. Es schreibt genau eine inverse `undo`-Buchung mit Referenz auf den Ursprung; Unique-Constraints verhindern doppeltes Undo. Ist die Gegenbuchung bei aktuellem Bestand nicht möglich, bleibt das Lager unverändert. Das Undo eines Startbestands stellt den vorherigen unbekannten Zustand nur dann wieder her, wenn keine spätere wirksame Bewegung mehr offen ist. Eine spätere Bewegung zählt auch dann als offen, wenn spätere Plus- und Minusbuchungen sich netto ausgleichen; sie muss selbst über die referenzierte Gegenbuchung aufgehoben worden sein. Vollständig rückgängig gemachte spätere Bewegungen erlauben das Undo und eine erneute Initialisierung. Ein direkter PATCH mit geändertem `quantity` wird abgelehnt; Artikeldaten bleiben separat editierbar.

Die Oberfläche speichert einen Idempotenzschlüssel pro ausstehender Buchungsabsicht in `sessionStorage` und hält ihn bis zu einer bestätigten Serverantwort. Bei unklarem Netzwerkfehler wird dieselbe Nutzlast mit demselben Schlüssel wiederholt; ein API-Replay bestätigt dann die bereits gespeicherte Bewegung, statt sie doppelt zu buchen. Dies gilt auch für Undo. Ein Wechsel des Scan-Modus entwertet die laufende Lookup-Generation und bricht den Request ab; verspätete Antworten dürfen keine Buchung starten. Direkt vor dem Senden einer Scan-Buchung prüft der API-Client den aktuell gewählten Modus erneut, auch wenn er zuvor noch eine Schreibsitzung holen oder erneuern musste.

## Zugriffsschutz

- Jeder HTTP-Zugriff bleibt auf Home Assistant Ingress begrenzt. Ingress authentifiziert Home-Assistant-Nutzer und leitet nur über den Supervisor-Proxy an die App weiter.
- Lese-Endpunkte benötigen keine zusätzliche Schreibsitzung. `POST`, `PATCH`, `DELETE` und Bewegungs-/Undo-Buchungen verlangen zusätzlich ein kurzlebiges Schreib-Token, das nur über Ingress bezogen werden kann und nie in einer URL steht.
- Die Schreibsitzung ist Schutz gegen ungewollte Cross-Site-Anfragen. Sie ersetzt keine getrennten Home-Assistant-Rollen und ist kein externer API-Schlüssel.
- CORS ist nicht freigegeben. Ein späterer Home-Assistant-Client muss einen dokumentierten, von Home Assistant authentifizierten Weg verwenden. Kein Browser-Code bekommt `SUPERVISOR_TOKEN`, Core-Token oder Geheimnisse aus der App-Konfiguration.
- Für externe Client-Authentifizierung, Berechtigungsbereiche und Widerruf ist vor direktem API-Zugriff eine eigene Sicherheitsprüfung erforderlich. Ingress wird dabei nicht umgangen.

## Eigenständige Home-Assistant-Integration

Die spätere Integration soll als `custom_components/ha_inventory` mit eigenem Config Flow und eigenem Release-Lebenszyklus entstehen. Sie wird REST-Client der Artikel-API, kein Datenbank-Client und keine weitere Artikeldatenbank.

Vorgesehene Schnittstellen:

- Sensoren für Artikelzahl, niedrige Bestände und optionale Artikel-/Bestandswerte.
- Aktionen für ausdrücklich angeforderte Bestandsänderungen und Einkaufslisten-Vorgänge.
- Ereignisse mit Artikel-ID und Änderungstyp, beispielsweise bei einer ausdrücklich gespeicherten Änderung.

Diese Integration wird in Version 0.3 noch nicht als installierbare Home-Assistant-Komponente ausgeliefert. Die aktuelle API ist über authentifizierten Ingress nutzbar; ein sicherer serverseitiger Integrationszugang außerhalb des Browsers muss erst festgelegt und getestet werden. Siehe [custom_components/ha_inventory/README.md](../custom_components/ha_inventory/README.md).

## Einkaufslisten und To-do-Listen

Eine spätere Anbindung kann die nativen Home-Assistant-To-do-Entitäten und die Einkaufsliste über deren dokumentierte Aktionen nutzen. Sie muss als explizite Nutzeraktion starten; weder ein Scan noch das Erledigen eines Einkaufslistenpunkts ändert automatisch den Lagerbestand.

Vor dem Hinzufügen prüft die Integration auf einen bereits offenen Eintrag. Sie hält die Operation pro Artikel-ID und Zielliste idempotent, verhindert parallele Doppelklicks und speichert eine Zuordnung zwischen Artikel-ID und Listen-Eintrag, soweit die To-do-API sie bereitstellt. Wenn eine Liste nur textbasierte Aktionen anbietet, darf kein automatisches Wiederholen erfolgen, solange nicht geklärt ist, ob der erste Aufruf bereits einen Eintrag erzeugt hat. Abschluss eines Listeneintrags aktualisiert den Lagerbestand nie stillschweigend.

Die Einkaufslisten- und To-do-Integration, Sensoren, Aktionen und Ereignisse sind geplant, aber in 0.2 nicht implementiert.
