import test from 'node:test';
import assert from 'node:assert/strict';
import { bookingForScan, buildMovementPayload, createIdempotencyKey, createScanDeduplicator } from '../stock-booking.mjs';

const counted = { tracking_mode: 'exact', quantity: 3, stock_status: 'known' };

test('view mode never books, receive chooses initialization for unknown stock', () => {
  assert.deepEqual(bookingForScan('view', counted), { action: 'view' });
  assert.deepEqual(bookingForScan('receive', { tracking_mode: 'simple', quantity: null }), { action: 'initialize' });
  assert.deepEqual(bookingForScan('receive', counted), { action: 'receive' });
});

test('consume mode only allows a known numeric quantity', () => {
  assert.deepEqual(bookingForScan('consume', counted), { action: 'consume' });
  assert.deepEqual(bookingForScan('consume', { tracking_mode: 'exact', quantity: null }), { action: 'unavailable' });
  assert.deepEqual(bookingForScan('consume', { tracking_mode: 'simple', quantity: null }), { action: 'unavailable' });
});

test('camera duplicate scans are suppressed briefly and allowed again afterward', () => {
  let now = 1000;
  const isDuplicate = createScanDeduplicator(1200, () => now);
  assert.equal(isDuplicate('000123'), false);
  now += 300;
  assert.equal(isDuplicate('000123'), true);
  assert.equal(isDuplicate('000124'), false);
  now += 1300;
  assert.equal(isDuplicate('000123'), false);
});

test('idempotency keys are created as unique request identifiers', () => {
  const keys = new Set(Array.from({ length: 20 }, () => createIdempotencyKey({})));
  assert.equal(keys.size, 20);
  assert.ok([...keys].every((key) => key.startsWith('scan-')));
});

test('movement payloads require explicit initialization and positive whole packs', () => {
  assert.deepEqual(buildMovementPayload('consume', 1, 'scan-1', { source: 'barcode' }), {
    action: 'consume', quantity: 1, source: 'barcode', idempotency_key: 'scan-1',
  });
  assert.deepEqual(buildMovementPayload('initialize', 4, 'scan-2', { trackingMode: 'inventory' }), {
    action: 'initialize', quantity: 4, source: 'manual', idempotency_key: 'scan-2',
    confirm_initial_stock: true, tracking_mode: 'inventory',
  });
  for (const quantity of [0, -1, 2.2, '1']) {
    assert.throws(() => buildMovementPayload('receive', quantity, 'scan-x'));
  }
});
