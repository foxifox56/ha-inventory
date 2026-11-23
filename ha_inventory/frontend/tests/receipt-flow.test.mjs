import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildReceiptImportPayload, compressReceiptImage, createReceiptIdempotencyKey,
  MAX_RECEIPT_UPLOAD_BYTES,
} from '../receipt-flow.mjs';

const receipt = { receipt_id: 'receipt-id', lines: [{ line_ids: [1] }] };

test('receipt import requires a receipt, explicit review and at least one selected line', () => {
  assert.throws(() => buildReceiptImportPayload(receipt, [], { idempotencyKey: 'key', confirmed: true }), /mindestens eine/);
  assert.throws(() => buildReceiptImportPayload(receipt, [{ line_ids: [1], decision: 'skip' }], { idempotencyKey: 'key' }), /bestätige/);
  assert.throws(() => buildReceiptImportPayload({}, [{ line_ids: [1], decision: 'skip' }], { idempotencyKey: 'key', confirmed: true }), /nicht mehr verfügbar/);
});

test('payload preserves corrected quantities, target choices and explicit duplicate override', () => {
  const payload = buildReceiptImportPayload(receipt, [
    { line_ids: [1, 2], label: 'Milch 1 l', decision: 'existing', item_id: 9, quantity: 2, learn_alias: true, tracking_mode: 'exact' },
  ], { idempotencyKey: 'receipt-once', confirmed: true, allowDuplicate: true });
  assert.equal(payload.confirmed, true);
  assert.equal(payload.idempotency_key, 'receipt-once');
  assert.equal(payload.allow_duplicate, true);
  assert.deepEqual(payload.rows[0], {
    line_ids: [1, 2], label: 'Milch 1 l', decision: 'existing', quantity: 2,
    learn_alias: true, replace_alias: false, tracking_mode: 'exact', item_id: 9,
  });
});

test('unknown products require an explicit new-item name and numeric tracking mode', () => {
  const base = { line_ids: [1], label: 'Haferdrink', decision: 'new', quantity: 1, name: 'Haferdrink' };
  assert.throws(() => buildReceiptImportPayload(receipt, [base], { idempotencyKey: 'key', confirmed: true }), /Bestandsmodell/);
  const payload = buildReceiptImportPayload(receipt, [{ ...base, tracking_mode: 'inventory' }], { idempotencyKey: 'key', confirmed: true });
  assert.equal(payload.rows[0].tracking_mode, 'inventory');
  assert.equal(payload.rows[0].barcode, '');
});

test('unsafe, fractional or zero receipt quantities are rejected before the API call', () => {
  for (const quantity of [0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => buildReceiptImportPayload(receipt, [
      { line_ids: [1], decision: 'existing', item_id: 1, quantity },
    ], { idempotencyKey: 'key', confirmed: true }));
  }
});

test('idempotency keys are unique and scoped to receipt actions', () => {
  const values = ['first-key', 'second-key'];
  const crypto = { randomUUID: () => values.shift() };
  assert.equal(createReceiptIdempotencyKey(crypto), 'receipt-first-key');
  assert.equal(createReceiptIdempotencyKey(crypto), 'receipt-second-key');
});

test('image preparation rotates and crops in memory, then returns bounded JPEG', async () => {
  const canvases = [];
  const canvasFactory = () => {
    const canvas = {
      width: 0, height: 0,
      getContext: () => ({ translate() {}, rotate() {}, drawImage() {} }),
      toBlob(callback, type) { callback(new Blob(['small-jpeg'], { type })); },
    };
    canvases.push(canvas);
    return canvas;
  };
  const blob = await compressReceiptImage({ name: 'bon.heic', size: 100 }, {
    rotation: 90, crop: { top: 0.1, right: 0.1, bottom: 0.1, left: 0.1 },
    bitmapFactory: async () => ({ width: 100, height: 200, close() {} }), canvasFactory,
  });
  assert.equal(blob.type, 'image/jpeg');
  assert.ok(blob.size < MAX_RECEIPT_UPLOAD_BYTES);
  assert.equal(canvases[0].width, 160);
  assert.equal(canvases[0].height, 80);
});

test('unsupported image decoding provides a manual recovery message', async () => {
  await assert.rejects(() => compressReceiptImage({ name: 'receipt.heic' }, {
    bitmapFactory: async () => { throw new Error('decode failed'); },
  }), /JPEG\/PNG|fotografiere/);
});

