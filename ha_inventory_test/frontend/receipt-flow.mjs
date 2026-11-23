export const MAX_RECEIPT_UPLOAD_BYTES = 6 * 1024 * 1024;
export const RECEIPT_UNDO_CONFIRM_MESSAGE = 'Alle Bestandsbuchungen dieses Kassenbons gemeinsam rückgängig machen? Neu angelegte Artikel bleiben mit unbekanntem Bestand bestehen; gelernte Produktzuordnungen bleiben erhalten. Das Undo wird vollständig abgelehnt, wenn eine Gegenbuchung unsicher wäre.';

export function receiptQuantityFieldValue(quantity) {
  return Number.isSafeInteger(quantity) && quantity > 0 && quantity <= 999
    ? String(quantity)
    : '';
}

export function parseReceiptQuantity(value) {
  const text = String(value ?? '').trim();
  if (!text) throw new Error('Gib für jede ausgewählte Position eine Menge ein.');
  const quantity = Number(text);
  if (!Number.isSafeInteger(quantity) || quantity < 1 || quantity > 999) {
    throw new Error('Die Menge muss eine ganze Zahl zwischen 1 und 999 sein.');
  }
  return quantity;
}

export function isReceiptQuantityValid(value) {
  try {
    parseReceiptQuantity(value);
    return true;
  } catch {
    return false;
  }
}

export function createReceiptRecognitionGuard(AbortControllerImpl = globalThis.AbortController) {
  let generation = 0;
  let activeController;
  return {
    begin() {
      activeController?.abort();
      activeController = new AbortControllerImpl();
      generation += 1;
      return { generation, signal: activeController.signal };
    },
    cancel() {
      generation += 1;
      activeController?.abort();
      activeController = undefined;
    },
    isCurrent(ticket) {
      return Boolean(ticket && ticket.generation === generation && !ticket.signal.aborted);
    },
  };
}

export async function prepareAndRecognizeReceipt(guard, ticket, file, {
  imageOptions, prepare, send,
}) {
  try {
    const image = await prepare(file, imageOptions);
    if (!guard.isCurrent(ticket)) return { stale: true };
    const result = await send(image, ticket.signal);
    if (!guard.isCurrent(ticket)) return { stale: true };
    return { stale: false, result };
  } catch (error) {
    if (!guard.isCurrent(ticket)) return { stale: true };
    throw error;
  }
}

export function buildReceiptImportPayload(receipt, decisions, {
  idempotencyKey, confirmed = false, allowDuplicate = false,
} = {}) {
  if (!receipt?.receipt_id) throw new Error('Der Bon ist nicht mehr verfügbar. Bitte erneut erkennen.');
  if (confirmed !== true) throw new Error('Bitte bestätige zuerst die geprüften Bonpositionen.');
  if (!Array.isArray(decisions) || decisions.length === 0) throw new Error('Wähle mindestens eine Bonposition.');
  if (typeof idempotencyKey !== 'string' || !idempotencyKey.trim()) throw new Error('Die sichere Importkennung fehlt.');
  const rows = decisions.map((row) => {
    if (!Array.isArray(row.line_ids) || row.line_ids.length === 0) throw new Error('Eine Position hat keine Bonzeile.');
    const result = {
      line_ids: row.line_ids,
      label: String(row.label ?? '').slice(0, 160),
      decision: row.decision,
    };
    if (row.decision === 'skip') return result;
    if (!Number.isSafeInteger(row.quantity) || row.quantity < 1) throw new Error('Prüfe die Menge jeder ausgewählten Position.');
    Object.assign(result, {
      quantity: row.quantity,
      learn_alias: row.learn_alias === true,
      replace_alias: row.replace_alias === true,
    });
    if (row.decision === 'existing') {
      if (!Number.isSafeInteger(row.item_id) || row.item_id < 1) throw new Error('Wähle einen passenden Lagerartikel.');
      result.item_id = row.item_id;
      if (row.tracking_mode) result.tracking_mode = row.tracking_mode;
    } else if (row.decision === 'new') {
      if (!String(row.name ?? '').trim()) throw new Error('Gib für neue Artikel einen Namen ein.');
      if (!['inventory', 'exact'].includes(row.tracking_mode)) throw new Error('Lege das Bestandsmodell ausdrücklich fest.');
      Object.assign(result, {
        name: String(row.name).trim(),
        barcode: String(row.barcode ?? '').trim(),
        category: String(row.category ?? 'Lebensmittel').trim(),
        location: String(row.location ?? '').trim(),
        unit: String(row.unit ?? 'Stück').trim(),
        tracking_mode: row.tracking_mode,
      });
    } else {
      throw new Error('Wähle einen Lagerartikel, einen neuen Artikel oder Überspringen.');
    }
    return result;
  });
  if (!rows.some((row) => row.decision !== 'skip')) throw new Error('Alle Positionen sind übersprungen.');
  return { confirmed: true, idempotency_key: idempotencyKey, allow_duplicate: allowDuplicate === true, rows };
}

export function createReceiptIdempotencyKey(cryptoImpl = globalThis.crypto) {
  if (cryptoImpl?.randomUUID) return `receipt-${cryptoImpl.randomUUID()}`;
  const random = Array.from({ length: 4 }, () => Math.random().toString(36).slice(2)).join('');
  return `receipt-${Date.now()}-${random}`;
}

export async function compressReceiptImage(file, {
  rotation = 0,
  crop = { top: 0, right: 0, bottom: 0, left: 0 },
  maxBytes = MAX_RECEIPT_UPLOAD_BYTES,
  maxEdge = 2400,
  bitmapFactory = (input) => createImageBitmap(input, { imageOrientation: 'from-image' }),
  canvasFactory = () => document.createElement('canvas'),
} = {}) {
  if (!file) throw new Error('Wähle zuerst ein Foto aus.');
  if (typeof bitmapFactory !== 'function') throw new Error('Bildverarbeitung ist in diesem Browser nicht verfügbar.');
  let bitmap;
  try {
    bitmap = await bitmapFactory(file);
  } catch {
    throw new Error('Dieses Bildformat kann Safari nicht lesen. Öffne den Bon als JPEG/PNG oder fotografiere ihn direkt.');
  }
  try {
    const angle = ((rotation % 360) + 360) % 360;
    if (![0, 90, 180, 270].includes(angle)) throw new Error('Ungültige Bilddrehung.');
    const rotatedWidth = angle % 180 === 0 ? bitmap.width : bitmap.height;
    const rotatedHeight = angle % 180 === 0 ? bitmap.height : bitmap.width;
    const left = Math.min(0.4, Math.max(0, Number(crop.left) || 0));
    const right = Math.min(0.4, Math.max(0, Number(crop.right) || 0));
    const top = Math.min(0.4, Math.max(0, Number(crop.top) || 0));
    const bottom = Math.min(0.4, Math.max(0, Number(crop.bottom) || 0));
    const sx = Math.round(rotatedWidth * left);
    const sy = Math.round(rotatedHeight * top);
    const sw = Math.round(rotatedWidth * (1 - left - right));
    const sh = Math.round(rotatedHeight * (1 - top - bottom));
    if (sw < 50 || sh < 50) throw new Error('Der Ausschnitt ist zu klein. Passe die Ränder an.');
    const scale = Math.min(1, maxEdge / Math.max(sw, sh));
    const canvas = canvasFactory();
    canvas.width = Math.max(1, Math.round(sw * scale));
    canvas.height = Math.max(1, Math.round(sh * scale));
    const context = canvas.getContext('2d', { alpha: false });
    if (!context) throw new Error('Bildverarbeitung ist fehlgeschlagen.');
    // Draw to an intermediate canvas only when rotation/crop is requested. The
    // intermediate exists only in memory and is released after this call.
    const rotated = canvasFactory();
    rotated.width = rotatedWidth;
    rotated.height = rotatedHeight;
    const rotatedContext = rotated.getContext('2d', { alpha: false });
    rotatedContext.translate(rotatedWidth / 2, rotatedHeight / 2);
    rotatedContext.rotate(angle * Math.PI / 180);
    rotatedContext.drawImage(bitmap, -bitmap.width / 2, -bitmap.height / 2);
    context.drawImage(rotated, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
    let quality = 0.88;
    let blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
    while (blob && blob.size > maxBytes && quality > 0.48) {
      quality -= 0.1;
      blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
    }
    if (!blob || blob.size > maxBytes) throw new Error('Das Foto bleibt zu groß. Wähle einen engeren Ausschnitt oder ein kleineres Bild.');
    return blob;
  } finally {
    bitmap.close?.();
  }
}
