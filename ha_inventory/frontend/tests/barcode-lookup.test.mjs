import test from 'node:test';
import assert from 'node:assert/strict';
import { lookupBarcodeValue } from '../barcode-lookup.mjs';
import { productPrefillValues } from '../product-prefill.mjs';

test('known local barcode opens the existing article without calling external product handler', async () => {
  const existing = { id: 8, name: 'Schrauben', quantity: 5, stock_status: 'known' };
  let opened;
  const result = await lookupBarcodeValue('0008', async () => ({ status: 'local', item: existing }), {
    found: (item) => { opened = item; },
    identified: () => assert.fail('known item must not use external product data'),
  });
  assert.equal(result.outcome, 'found');
  assert.equal(opened, existing);
  assert.equal(existing.quantity, 5);
});

test('known alphanumeric item code opens its local article unchanged', async () => {
  const existing = {
    id: 18, name: 'Akkuschrauber', barcode: 'TOOL-001',
    tracking_mode: 'exact', quantity: 3, stock_status: 'known',
  };
  let opened;
  const result = await lookupBarcodeValue(' TOOL-001 ', async (code) => {
    assert.equal(code, 'TOOL-001');
    return { status: 'local', item: existing };
  }, {
    found: (item) => { opened = item; },
    missing: () => assert.fail('known alphanumeric item must open locally'),
  });
  assert.equal(result.outcome, 'found');
  assert.equal(opened, existing);
  assert.equal(existing.quantity, 3);
  assert.equal(existing.stock_status, 'known');
});

test('identified product becomes editable form suggestions and preserves barcode zeroes', async () => {
  const product = {
    name: 'Haferdrink', brand: 'Beispiel', product_size: '1 l', category: 'Lebensmittel',
    image_url: 'https://images.openfoodfacts.org/example.jpg',
    image_license: 'CC BY-SA',
    data_source: 'Open Food Facts', source_url: 'https://world.openfoodfacts.org/product/0000123',
  };
  let prefills;
  let pending = false;
  let settled = false;
  const result = await lookupBarcodeValue('0000123', async (barcode) => ({
    status: 'identified', barcode, product,
  }), {
    pending: () => { pending = true; },
    identified: (barcode, candidate) => { prefills = productPrefillValues(barcode, candidate); },
    settled: () => { settled = true; },
    saved: () => assert.fail('lookup must never save a product'),
  });
  assert.equal(result.outcome, 'identified');
  assert.equal(pending, true);
  assert.equal(settled, true);
  assert.equal(prefills.barcode, '0000123');
  assert.equal(prefills.name, 'Haferdrink');
  assert.equal(prefills.brand, 'Beispiel');
  assert.equal(prefills.product_size, '1 l');
  assert.equal(prefills.image_url, product.image_url);
  assert.equal(prefills.image_license, 'CC BY-SA');
  assert.equal(prefills.source_url, product.source_url);
});

test('partial product metadata fills what exists and unknown barcode stays in normal form', async () => {
  let values;
  const product = { name: '', brand: 'Marke' };
  await lookupBarcodeValue('0011', async () => ({ status: 'identified', product }), {
    identified: (barcode, candidate) => { values = productPrefillValues(barcode, candidate); },
  });
  assert.equal(values.barcode, '0011');
  assert.equal(values.name, '');
  assert.equal(values.brand, 'Marke');
  assert.equal(values.category, 'Sonstiges');
  assert.equal(values.image_url, '');
});

test('not found and provider failure both keep the entered barcode for manual entry', async () => {
  const outcomes = [];
  await lookupBarcodeValue('0012', async () => ({ status: 'not_found' }), {
    missing: (barcode) => outcomes.push(['missing', barcode]),
  });
  const failure = new Error('offline');
  await lookupBarcodeValue('0013', async () => { throw failure; }, {
    failed: (error, barcode) => outcomes.push(['failed', error.message, barcode]),
  });
  assert.deepEqual(outcomes, [['missing', '0012'], ['failed', 'offline', '0013']]);
});

test('unknown alphanumeric code uses manual entry and never calls a product provider directly', async () => {
  let manualCode;
  const result = await lookupBarcodeValue('TOOL-002', async (code) => {
    assert.equal(code, 'TOOL-002');
    return { status: 'not_found', barcode: code };
  }, {
    missing: (code) => { manualCode = code; },
    identified: () => assert.fail('alphanumeric unknowns are not Open Facts lookups'),
  });
  assert.equal(result.outcome, 'missing');
  assert.equal(manualCode, 'TOOL-002');
});

test('rapid sequential product lookups retry rate limits with bounded visible waits', async () => {
  const requests = [];
  const waits = [];
  const waitingStatuses = [];
  const foundProducts = [];
  const lookup = async (barcode) => {
    requests.push(barcode);
    if (requests.filter((code) => code === barcode).length === 1) {
      const error = new Error('Kurz warten');
      error.code = 'product_lookup_rate_limited';
      error.retryAfterSeconds = 2.5;
      throw error;
    }
    return { status: 'identified', product: { name: `Produkt ${barcode}` } };
  };

  for (const barcode of ['000101', '000102', '000103']) {
    const result = await lookupBarcodeValue(barcode, lookup, {
      waiting: (code, seconds, attempt) => waitingStatuses.push([code, seconds, attempt]),
      identified: (code, product) => foundProducts.push([code, product.name]),
      failed: (error) => assert.fail(error.message),
      saved: () => assert.fail('lookup must never save a product'),
    }, {
      wait: async (milliseconds) => { waits.push(milliseconds); },
      maxRetries: 2,
      maxWaitMs: 6000,
    });
    assert.equal(result.outcome, 'identified');
  }

  assert.deepEqual(requests, ['000101', '000101', '000102', '000102', '000103', '000103']);
  assert.deepEqual(waits, [2550, 2550, 2550]);
  assert.deepEqual(waitingStatuses, [
    ['000101', 2.5, 1], ['000102', 2.5, 1], ['000103', 2.5, 1],
  ]);
  assert.equal(foundProducts.length, 3);
});

test('a queued lookup can be cancelled for immediate manual entry', async () => {
  const controller = new AbortController();
  let attempts = 0;
  let cancelled = false;
  let beginWaiting;
  const waiting = new Promise((resolve) => { beginWaiting = resolve; });
  const resultPromise = lookupBarcodeValue('000103', async () => {
    attempts += 1;
    const error = new Error('Kurz warten');
    error.code = 'product_lookup_rate_limited';
    error.retryAfterSeconds = 4.1;
    throw error;
  }, {
    waiting: beginWaiting,
    cancelled: () => { cancelled = true; },
  }, {
    signal: controller.signal,
    wait: (_milliseconds, signal) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => {
        const error = new Error('aborted');
        error.name = 'AbortError';
        reject(error);
      }, { once: true });
    }),
  });
  await waiting;
  controller.abort();
  const result = await resultPromise;
  assert.equal(result.outcome, 'cancelled');
  assert.equal(cancelled, true);
  assert.equal(attempts, 1);
});

test('temporary provider failures stop after the configured retry and time budget', async () => {
  let attempts = 0;
  let waits = 0;
  let failureMessage = '';
  const result = await lookupBarcodeValue('000104', async () => {
    attempts += 1;
    const error = new Error('Rate-Limit bleibt aktiv');
    error.code = 'product_lookup_rate_limited';
    error.retryAfterSeconds = 5;
    throw error;
  }, {
    failed: (error, barcode) => {
      assert.equal(barcode, '000104');
      failureMessage = error.message;
    },
  }, {
    wait: async () => { waits += 1; },
    maxRetries: 2,
    maxWaitMs: 12000,
  });
  assert.equal(result.outcome, 'failed');
  assert.equal(attempts, 3);
  assert.equal(waits, 2);
  assert.equal(failureMessage, 'Rate-Limit bleibt aktiv');
});
