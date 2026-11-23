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
