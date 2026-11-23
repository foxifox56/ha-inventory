import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildReceiptImportPayload, compressReceiptImage, createReceiptIdempotencyKey,
  createReceiptRecognitionGuard, isReceiptQuantityValid, MAX_RECEIPT_UPLOAD_BYTES,
  parseReceiptQuantity, prepareAndRecognizeReceipt, receiptQuantityFieldValue,
  RECEIPT_UNDO_CONFIRM_MESSAGE,
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

test('unknown receipt quantities stay blank and require an explicit valid correction', () => {
  assert.equal(receiptQuantityFieldValue(null), '');
  assert.equal(receiptQuantityFieldValue(undefined), '');
  assert.equal(receiptQuantityFieldValue(2), '2');
  assert.equal(isReceiptQuantityValid(''), false);
  assert.equal(isReceiptQuantityValid('1.5'), false);
  assert.equal(isReceiptQuantityValid('2'), true);
  assert.throws(() => parseReceiptQuantity(''), /Menge ein/);
  assert.equal(parseReceiptQuantity('2'), 2);
  assert.throws(() => buildReceiptImportPayload(receipt, [
    { line_ids: [1], decision: 'existing', item_id: 1, quantity: null },
  ], { idempotencyKey: 'key', confirmed: true }), /Menge/);
  const corrected = buildReceiptImportPayload(receipt, [
    { line_ids: [1], decision: 'existing', item_id: 1, quantity: parseReceiptQuantity('2') },
  ], { idempotencyKey: 'key', confirmed: true });
  assert.equal(corrected.rows[0].quantity, 2);
});

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

test('changing the selected photo during image processing invalidates the older OCR request', async () => {
  const guard = createReceiptRecognitionGuard();
  const ticket = guard.begin();
  const processing = deferred();
  let requests = 0;
  const pending = prepareAndRecognizeReceipt(guard, ticket, { name: 'photo-a' }, {
    prepare: () => processing.promise,
    send: async () => { requests += 1; return { receipt_id: 'old' }; },
  });
  guard.cancel();
  processing.resolve(new Blob(['photo-a']));
  assert.deepEqual(await pending, { stale: true });
  assert.equal(requests, 0);
});

test('changing the selected photo during OCR aborts and discards the late response', async () => {
  const guard = createReceiptRecognitionGuard();
  const ticket = guard.begin();
  const ocr = deferred();
  const started = deferred();
  let signal;
  const pending = prepareAndRecognizeReceipt(guard, ticket, { name: 'photo-a' }, {
    prepare: async () => new Blob(['photo-a']),
    send: (_blob, requestSignal) => { signal = requestSignal; started.resolve(); return ocr.promise; },
  });
  await started.promise;
  guard.cancel();
  assert.equal(signal.aborted, true);
  ocr.resolve({ receipt_id: 'old-photo-result' });
  assert.deepEqual(await pending, { stale: true });
});

test('a newer photo recognition remains current when an older OCR response arrives late', async () => {
  const guard = createReceiptRecognitionGuard();
  const oldOcr = deferred();
  const oldStarted = deferred();
  const oldTicket = guard.begin();
  const oldPending = prepareAndRecognizeReceipt(guard, oldTicket, { name: 'photo-a' }, {
    prepare: async () => new Blob(['photo-a']),
    send: (_blob, signal) => { oldStarted.resolve(); return oldOcr.promise.then((value) => {
      if (signal.aborted) return value;
      return value;
    }); },
  });
  await oldStarted.promise;
  const newTicket = guard.begin();
  const newPending = prepareAndRecognizeReceipt(guard, newTicket, { name: 'photo-b' }, {
    prepare: async () => new Blob(['photo-b']),
    send: async () => ({ receipt_id: 'photo-b-result' }),
  });
  oldOcr.resolve({ receipt_id: 'photo-a-result' });
  assert.deepEqual(await oldPending, { stale: true });
  assert.deepEqual(await newPending, { stale: false, result: { receipt_id: 'photo-b-result' } });
});

test('receipt undo confirmation explains which imported data remains', () => {
  assert.match(RECEIPT_UNDO_CONFIRM_MESSAGE, /Bestandsbuchungen/);
  assert.ok(RECEIPT_UNDO_CONFIRM_MESSAGE.includes('Neu angelegte Artikel bleiben'));
  assert.match(RECEIPT_UNDO_CONFIRM_MESSAGE, /gelernte Produktzuordnungen bleiben/);
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

