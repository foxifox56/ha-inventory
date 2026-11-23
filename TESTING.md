# Testprotokoll – HA Inventory v0.4

Stand: 23.11.2026 · Branch `development/v0.4` · Zielbranch des Review-PR: `development/v0.3`.

## Lokale Prüfungen

Die folgenden Prüfungen liefen in der Entwicklungsumgebung auf temporären SQLite-Datenbanken und mit simulierten HTTP-/OCR-Antworten. Sie nehmen keine Verbindung zum produktiven Home Assistant oder Raspberry Pi auf.

| Prüfung | Ergebnis |
| --- | --- |
| Backendtests | **78 bestanden**. Enthalten sind API-/Ingress-/Write-Session-Schutz, v6→v7-Migration, lokale Fotoeingabe und Validierung, REWE-/Kaufland-/generische Bonzeilen, Mengen-/Preisabgrenzung, Produktzuordnung und Alias-Lernen, Dublettenwarnung, explizite Bestätigung, Idempotenz, atomarer Sammelimport und vollständiges Rückgängigmachen. Tesseract-Timeout und fehlende Sprachdaten werden als begrenzte, verständliche Fehler getestet. |
| Frontendtests | **44 bestanden**. Enthalten sind bonbezogene Payload- und Mengenvalidierung, explizite Importbestätigung, sichere Wiederholungsschlüssel, Foto-Rotation/Zuschnitt/Kompression im Speicher, HEIC-Fehleralternative sowie bestehende Scanner-, Bestands- und Navigationsregressionen. |
| Python-Syntax | `python -m compileall -q backend` bestanden. |
| JavaScript-Syntax | `node --check` für `frontend/*.js`, `frontend/*.mjs` und `frontend/vendor/*.mjs` bestanden. |
| Konfiguration | `ha_inventory/config.yaml` und `.github/workflows/ci.yml` erfolgreich mit PyYAML geladen. Add-on-Metadaten deklarieren `aarch64` und `amd64`, Version `0.4.0` und `backup: cold`. |
| Lokale OCR-Funktionsprobe | Synthetischer REWE-Bon wurde mit dem lokal installierten Tesseract tatsächlich erkannt; Multiplikator `2 X MILCH` ergab Menge 2. Lokal ist nur `eng` installiert. Dies ist kein Docker-, `deu`- oder Hardwaretest. |
| Lokaler Docker-Smoke-Test | **Nicht durchgeführt**: Die Entwicklungsumgebung stellt keine Docker-CLI bereit. |
| GitHub Actions Push-Workflow | **Erfolgreich**, [Run #41](https://github.com/foxifox56/ha-inventory/actions/runs/45259928128), Commit `5576ca922f1609d7626f52b1af5cf691d7c476f4`: Backend-/Frontendtests, AMD64- und ARM64-Build-Smokes sowie tatsächliche lokale Tesseract-OCR mit `deu` + `eng`. |
| GitHub Actions PR-Workflow | **Erfolgreich**, [Run #42](https://github.com/foxifox56/ha-inventory/actions/runs/45260087479), derselbe Commit: Backend-/Frontendtests, AMD64- und ARM64-Build-Smokes sowie tatsächliche lokale Tesseract-OCR mit `deu` + `eng`. |

Befehle aus `ha_inventory/`:

```bash
python -m unittest discover -s backend/tests -v
node --test frontend/tests/*.test.mjs
python -m compileall -q backend
for file in frontend/*.js frontend/*.mjs frontend/vendor/*.mjs; do node --check "$file" || exit 1; done
python - <<'PY'
import yaml
for path in ('config.yaml', '../.github/workflows/ci.yml'):
    with open(path, encoding='utf-8') as stream:
        yaml.safe_load(stream)
PY
```

## Container-Smoke in GitHub Actions

Der CI-Workflow baut und startet das Home Assistant-App-Image getrennt für `linux/amd64` und `linux/arm64`. In jedem Container prüft `scripts/container-smoke.sh`:

- App-Start und Ingress-Ablehnung direkter, nicht autorisierter Requests.
- Vorhandensein von Tesseract-Sprachdaten `deu` und `eng`.
- Echte lokale OCR eines synthetischen REWE-Bons, einschließlich Erkennung von `2 X MILCH` als Menge 2.
- Dass die reine Erkennung weder Artikel noch Bestand anlegt.
- Buchung, idempotentes Replay, Undo, Bewegungsverlauf und Persistenz nach Container-Neustart.

Diese Prüfungen belegen die Container-Laufzeit unter den beiden Zielarchitekturen; sie sind keine Raspberry-Pi-, HAOS-Supervisor- oder iPhone-Kameratests. Push-Run #41 und PR-Run #42 waren auf dem v0.4-Codecommit erfolgreich; beide führten das `receipt-ocr`-Kommando in beiden Architekturen aus. Diese Container-Smokes sind reproduzierbar und enthalten keine echten persönlichen Belege.

## Manuelle iPhone-Prüfung über Home Assistant Ingress / Nabu Casa

Echter iPhone-, Safari-, Home-Assistant-Ingress- und Nabu-Casa-Test: **nicht durchgeführt**. Dafür wird ein separates Testsystem benötigt. Keine direkte App-IP oder einen offenen Port verwenden.

1. Auf dem iPhone Home Assistant über die lokale HTTPS-URL oder außerhalb des Heimnetzes über die eigene Nabu-Casa-URL öffnen. HA Inventory innerhalb Home Assistant über **Einstellungen → Apps → HA Inventory → Öffnen** aufrufen, damit Ingress und HA-Authentifizierung erhalten bleiben.
2. Über **Bon** ein Foto aufnehmen und anschließend ein Bild aus der Fotomediathek auswählen. Kamera-/Dateiauswahl, Vorschau, Rotation, Zuschnitt und verständliche Fehlermeldung bei nicht dekodierbarem HEIC prüfen.
3. Einen REWE-Bon mit künstlich/entpersonalisiertem Inhalt testen: bekannte Artikel zuordnen, Mengen korrigieren und eine Position auslassen. Vor dem gemeinsamen Bestätigen dürfen keine Artikel oder Bestände verändert werden.
4. Einen Kaufland-Bon mit Multiplikator, Pfand, Rabatt, Kartenzahlung und Summe prüfen. Nur Produktpositionen dürfen zum Import angeboten werden; unklare Mengen müssen sichtbar zur Kontrolle markiert sein.
5. Eine unbekannte Belegbezeichnung manuell einem bestehenden Artikel zuordnen und Alias-Lernen aktivieren. Erst nach erfolgreichem Import darf der Alias vorgeschlagen werden.
6. Eine neue Position manuell als Artikel einrichten. Lagerort und Bestandsmodell ausdrücklich wählen; bei unbekanntem/einfachem Bestand darf keine stillschweigende Initialisierung mit 0 stattfinden.
7. Den Import bestätigen und prüfen, dass alle ausgewählten Artikel exakt einmal gebucht werden und der Verlauf `source=receipt`, Bon-ID sowie Bonzeilen enthält. Direkt nach einem verlorenen Antwortsignal dieselbe Aktion wiederholen: gleicher Idempotenzschlüssel, keine zweite Buchung.
8. Dasselbe Bonfoto erneut erkennen. Die UI muss eine Dublettenwarnung zeigen und vor einem weiteren Import eine bewusste Bestätigung verlangen. Zwei echte, ähnliche Einkäufe dürfen nach Prüfung weiterhin importierbar sein.
9. Den gesamten Bon-Import rückgängig machen. Alle Bewegungen müssen gemeinsam zurückgenommen werden. Eine absichtlich unsichere Gegenbuchung nach späterer Entnahme muss vollständig abgelehnt werden, ohne Teil-Undo.
10. App neu öffnen und Artikel, Alias, Importstatus, Bewegungsverlauf und Undo-Ergebnis prüfen. Rohfoto und vollständiger OCR-Text dürfen nicht dauerhaft gespeichert sein.

## Grenzen und nicht durchgeführte Tests

- Echter iPhone-Kamera-/Safari-/HA-Ingress-/Nabu-Casa-Test: **nicht durchgeführt**.
- Echter Raspberry-Pi-4-, HAOS-64-bit- und Supervisor-Installations-/Backup-Test: **nicht durchgeführt**. Es wurde nichts auf einem produktiven System installiert oder geändert.
- Lokaler Docker-Smoke-Test: **nicht durchgeführt**, weil Docker nicht verfügbar ist. Die erfolgreichen Workflow-Läufe #41/#42 sind oben verlinkt.
- Lokale OCR-Probe verwendete nur Englisch (`eng`); `deu` + `eng` wurde durch die tatsächlichen Containerläufe in GitHub Actions geprüft.
- Live-OCR mit echten, persönlichen REWE-/Kaufland-Belegen: **nicht durchgeführt**. CI verwendet synthetische Belege; Bonlayouts und Druckqualität variieren.
- HEIC-Konvertierung hängt vom iOS-Browser ab. Wenn das Foto nicht dekodiert werden kann, muss der Nutzer ein kompatibles Bild wählen oder erneut aufnehmen.
- OCR, Händlererkennung und schwache Beleg-Fingerprints sind fehlertolerante Vorschläge. Jede Zeile, Menge und Zuordnung muss geprüft werden. Ein Fingerprint kann ähnliche Einkäufe als möglichen Duplikatfall markieren; die UI verlangt dann eine ausdrückliche Entscheidung.
- Produktbezeichnungen ohne EAN bleiben manuelle Vorschläge; der Belegimport fragt keine externen Produktdatenbanken ab.
- Keine automatische Bestandsänderung durch Foto/OCR: nur ein ausdrücklich bestätigter Sammelimport bucht. Wenn irgendeine Importzeile fehlschlägt, wird die gesamte SQLite-Transaktion zurückgerollt. Das gemeinsame Undo wird ebenfalls vollständig ausgeführt oder vollständig abgelehnt.
