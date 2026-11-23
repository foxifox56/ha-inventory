import test from 'node:test';
import assert from 'node:assert/strict';
import {
  bookingForScan, buildMovementPayload, createIdempotencyKey, createMovementIntentStore,
  createScanDeduplicator, createScanRequestGuard, parseScanQuantity,
} from '../stock-booking.mjs';

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
  assert.deepEqual(buildMovementPayload('initialize', 0, 'zero-baseline', { trackingMode: 'exact' }), {
    action: 'initialize', quantity: 0, source: 'manual', idempotency_key: 'zero-baseline',
    confirm_initial_stock: true, tracking_mode: 'exact',
  });
  assert.throws(() => buildMovementPayload('consume', 0, 'zero-consume'));
});

test('in-flight barcode results are invalidated by a scan-mode change', async () => {
  const guard = createScanRequestGuard();
  const request = guard.begin('consume');
  let mode = 'consume';
  let booked = false;
  let resolveLookup;
  const lookup = new Promise((resolve) => { resolveLookup = resolve; });
  const handling = lookup.then(() => {
    if (guard.isCurrent(request, mode)) booked = true;
  });
  mode = 'view';
  guard.invalidate();
  resolveLookup({ status: 'local', item: counted });
  await handling;
  assert.equal(booked, false);
  assert.equal(guard.isCurrent(request, mode), false);
});

test('a lost response is retried with the same durable key and books only once', async () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
  let nextKey = 0;
  const keys = () => `intent-${++nextKey}`;
  const originalStore = createMovementIntentStore(storage, keys);
  const details = { itemId: 42, action: 'consume', quantity: 1, source: 'barcode' };
  const firstIntent = originalStore.getOrCreate(details);
  const committedKeys = new Set();
  let changes = 0;
  const send = (intent, loseResponse) => {
    if (!committedKeys.has(intent.idempotencyKey)) {
      committedKeys.add(intent.idempotencyKey);
      changes += 1;
    }
    if (loseResponse) throw new Error('connection lost after commit');
  };
  assert.throws(() => send(firstIntent, true), /connection lost/);

  const reloadedStore = createMovementIntentStore(storage, keys);
  const retryIntent = reloadedStore.getOrCreate(details);
  assert.equal(retryIntent.idempotencyKey, firstIntent.idempotencyKey);
  send(retryIntent, false);
  reloadedStore.complete(retryIntent);
  assert.equal(changes, 1);
  assert.notEqual(reloadedStore.getOrCreate(details).idempotencyKey, firstIntent.idempotencyKey);
});

test('undo requests retain their key until the response is confirmed', () => {
  const store = createMovementIntentStore({ getItem: () => null, setItem: () => {} }, (() => {
    let key = 0;
    return () => `undo-${++key}`;
  })());
  const details = { itemId: 12, action: 'undo', quantity: 1, source: 'ui', undoOfMovementId: 81 };
  const first = store.getOrCreate(details);
  const retry = store.getOrCreate(details);
  assert.equal(first.idempotencyKey, retry.idempotencyKey);
  store.complete(retry);
  assert.notEqual(store.getOrCreate(details).idempotencyKey, first.idempotencyKey);
});

test('scan booking quantities reject fractions, negatives, and unsafe values without rounding', () => {
  assert.equal(parseScanQuantity('3'), 3);
  for (const value of ['', '0', '-1', '2.8', '1e2', '9007199254740992']) {
    assert.equal(parseScanQuantity(value), null, `expected ${value} to be invalid`);
  }
});
