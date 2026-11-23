# HA Inventory TEST (v0.4)

**Eigenständige Test-App – bestehende HA-Inventory-Installation nicht ersetzen.**

- App-Slug: `ha-inventory-test`, unabhängig von `ha-inventory`.
- Separater persistenter App-Speicher `/data`, damit eigene Test-Artikel und SQLite-Datenbank.
- Start nur manuell (`boot: manual`), ausschließlich Ingress, **keine** Host-Portfreigabe.
- Unterstützt `aarch64` (Raspberry Pi 4, 64-bit HAOS) und `amd64`.
- Nutzt dieselbe v0.4-Anwendung mit lokaler Tesseract-OCR und Kassenbon-Sammelimport.

## Sichere Installation – erst nach Review und Backup

Empfohlen: In Home Assistant den Ordner `ha_inventory_test/` separat unter `local_apps/ha_inventory_test/` bereitstellen, dann unter **Einstellungen → Apps → Local apps** aktualisieren und nur **HA Inventory TEST (v0.4)** installieren.

Alternativ: GitHub-Repository `https://github.com/foxifox56/ha-inventory#development/v0.4-test-app` als Quelle verwenden. Diese Branch-Quelle enthält **beide Apps**; nur die Test-App mit dem Slug `ha-inventory-test` auswählen. Falls Home Assistant anstelle der Test-App nur eine Aktualisierung der regulären App anbietet, **abbrechen**.

Vor Installation vollständiges Home-Assistant-Backup inklusive App-Daten erstellen. Produktive `ha-inventory`-App weder deinstallieren noch überschreiben. Der Weg wurde noch nicht auf einem echten Supervisor getestet; GitHub-Änderungen allein installieren nichts.

## Test

App über Home Assistant/Nabu Casa am iPhone öffnen. Mit **Testartikeln** REWE-/Kaufland-Bons fotografieren, Mengen prüfen, gemeinsam einlagern, denselben Bon erneut scannen (Duplikatwarnung) und Sammel-Undo prüfen. Danach Persistenz durch Neustart der **Test-App** prüfen. Die Test-App nur bei Bedarf starten, denn OCR beansprucht Ressourcen auf dem Pi.

Neu angelegte Testartikel und gelernte Zuordnungen bleiben beim Buchungs-Undo bewusst erhalten. Kein gemeinsamer Datenbestand mit der regulären App.
