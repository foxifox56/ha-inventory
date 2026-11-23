import test from 'node:test';
import assert from 'node:assert/strict';
import { isLowStock, simpleStockStatus, stockDetail, stockLabel, trackingModeLabel } from '../stock.mjs';
import { lookupBarcodeValue } from '../barcode-lookup.mjs';

test('simple stock distinguishes unknown, present, and empty', () => {
  const base = { tracking_mode: 'simple', quantity: null, unit: 'Stück' };
  assert.equal(stockLabel({ ...base, stock_status: 'unknown' }), 'Bestand unbekannt');
  assert.equal(stockLabel({ ...base, stock_status: 'present' }), 'Vorhanden');
  assert.equal(stockLabel({ ...base, stock_status: 'out_of_stock' }), 'Nicht vorhanden');
});

test('switching a numeric item to simple mode selects a valid unknown status', () => {
  assert.equal(simpleStockStatus('known'), 'unknown');
  assert.equal(simpleStockStatus(''), 'unknown');
  assert.equal(simpleStockStatus('present'), 'present');
});

test('estimated and exact quantities are labelled differently', () => {
  const item = { quantity: 2, unit: 'Packung', stock_status: 'known' };
  assert.equal(stockLabel({ ...item, tracking_mode: 'inventory' }), 'ca. 2 Packung');
  assert.equal(stockLabel({ ...item, tracking_mode: 'exact' }), '2 Packung');
  assert.equal(trackingModeLabel('exact'), 'Exakter Bestand');
});

test('unknown numeric quantities stay visibly unknown', () => {
  assert.equal(
    stockDetail({ tracking_mode: 'exact', stock_status: 'unknown', quantity: null }),
    'Bestand unbekannt',
  );
});

test('low-stock warnings require a known numeric count', () => {
  assert.equal(isLowStock({ tracking_mode: 'exact', quantity: 0, minimum_quantity: 1 }), true);
  assert.equal(isLowStock({ tracking_mode: 'exact', quantity: null, minimum_quantity: 1 }), false);
  assert.equal(isLowStock({ tracking_mode: 'simple', quantity: null, minimum_quantity: 1 }), false);
});

test('a known barcode opens the item details callback without changing stock', async () => {
  const item = { id: 4, name: 'Olivenöl', tracking_mode: 'simple', stock_status: 'unknown', quantity: null };
  let opened;
  const result = await lookupBarcodeValue('  0004  ', async (barcode) => {
    assert.equal(barcode, '0004');
    return { status: 'local', item };
  }, {
    found: (foundItem) => { opened = foundItem; },
    missing: () => assert.fail('known barcode should not start item creation'),
    failed: (error) => { throw error; },
  });
  assert.equal(result.outcome, 'found');
  assert.deepEqual(opened, item);
  assert.equal(item.quantity, null);
  assert.equal(item.stock_status, 'unknown');
});

test('an unknown barcode is passed to the new-item callback', async () => {
  let newBarcode;
  const result = await lookupBarcodeValue('0099', async () => ({ status: 'not_found' }), {
    found: () => assert.fail('unknown barcode cannot open an existing item'),
    missing: (barcode) => { newBarcode = barcode; },
    failed: (error) => { throw error; },
  });
  assert.equal(result.outcome, 'missing');
  assert.equal(newBarcode, '0099');
});
