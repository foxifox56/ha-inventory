import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const scanCopy = html.match(/<p class="scan-copy">([\s\S]*?)<\/p>/)?.[1] ?? '';

test('scanner guidance distinguishes read-only, confirmed receipt, and immediate consumption', () => {
  assert.match(scanCopy, /Ansehen: öffnet bekannte Artikel nur lesend/);
  assert.match(scanCopy, /Einlagern:.*bestätige die Buchung; erst danach steigt der Bestand/);
  assert.match(scanCopy, /Verbrauchen:.*bucht die gewählte Menge sofort ab/);
  assert.match(scanCopy, /standardmäßig 1 Einheit, ohne weitere Bestätigung/);
  assert.match(scanCopy, /im Verlauf rückgängig machen/);
  assert.match(scanCopy, /Unbekannte Codes werden nicht automatisch gespeichert oder gebucht/);
});
