export const SCAN_MODES = Object.freeze(['view', 'receive', 'consume']);

export function bookingForScan(mode, item) {
  if (!SCAN_MODES.includes(mode)) return { action: 'invalid' };
  if (mode === 'view') return { action: 'view' };
  const known = item?.tracking_mode !== 'simple'
    && item?.quantity !== null && item?.quantity !== undefined
    && item?.stock_status === 'known';
  if (mode === 'receive') return { action: known ? 'receive' : 'initialize' };
  if (!known) return { action: 'unavailable' };
  return { action: 'consume' };
}

export function createScanDeduplicator(windowMs = 1200, clock = () => Date.now()) {
  const recent = new Map();
  return (rawCode) => {
    const code = String(rawCode ?? '').trim();
    if (!code) return true;
    const now = clock();
    for (const [value, at] of recent) {
      if (now - at > windowMs) recent.delete(value);
    }
    const previous = recent.get(code);
    if (previous !== undefined && now - previous <= windowMs) return true;
    recent.set(code, now);
    return false;
  };
}

export function createIdempotencyKey(cryptoImpl = globalThis.crypto) {
  if (typeof cryptoImpl?.randomUUID === 'function') return cryptoImpl.randomUUID();
  return `scan-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

/** Keep a request key for the exact user intent until a response confirms it. */
export function createMovementIntentStore(storage, keyFactory = createIdempotencyKey) {
  let persistence = storage;
  if (persistence === undefined) {
    try { persistence = globalThis.sessionStorage; } catch { persistence = undefined; }
  }
  const storageKey = 'ha-inventory.pending-movements.v1';
  const pending = new Map();

  try {
    const stored = JSON.parse(persistence?.getItem(storageKey) || '[]');
    if (Array.isArray(stored)) {
      for (const entry of stored) {
        if (Array.isArray(entry) && typeof entry[0] === 'string' && typeof entry[1] === 'string') {
          pending.set(entry[0], { idempotencyKey: entry[1], intent: entry[2] || null });
        }
      }
    }
  } catch { /* Storage can be unavailable or contain stale data; memory fallback is safe. */ }

  function persist() {
    try {
      persistence?.setItem(storageKey, JSON.stringify(
        [...pending.entries()].map(([fingerprint, entry]) => [fingerprint, entry.idempotencyKey, entry.intent]),
      ));
    } catch { /* memory fallback */ }
  }

  function fingerprint(intent) {
    return JSON.stringify([
      String(intent.itemId), intent.action, intent.quantity, intent.source || 'manual',
      intent.trackingMode || '', intent.undoOfMovementId ?? null,
    ]);
  }

  return {
    getOrCreate(intent) {
      const id = fingerprint(intent);
      const descriptor = {
        itemId: String(intent.itemId), action: intent.action, quantity: intent.quantity,
        source: intent.source || 'manual', trackingMode: intent.trackingMode || '',
        undoOfMovementId: intent.undoOfMovementId ?? null,
      };
      let entry = pending.get(id);
      if (!entry) {
        entry = { idempotencyKey: keyFactory(), intent: descriptor };
        pending.set(id, entry);
        persist();
      }
      return { ...descriptor, idempotencyKey: entry.idempotencyKey, fingerprint: id };
    },
    findPending(itemId) {
      return [...pending.entries()]
        .filter(([, entry]) => entry.intent?.itemId === String(itemId))
        .map(([fingerprintValue, entry]) => ({
          ...entry.intent, idempotencyKey: entry.idempotencyKey, fingerprint: fingerprintValue,
        }));
    },
    complete(intent) {
      if (intent && pending.get(intent.fingerprint)?.idempotencyKey === intent.idempotencyKey) {
        pending.delete(intent.fingerprint);
        persist();
      }
    },
  };
}

/** Invalidates a lookup when its user-confirmed scan mode changes. */
export function createScanRequestGuard() {
  let generation = 0;
  return {
    begin(mode) { return { generation: ++generation, mode }; },
    invalidate() { generation += 1; },
    isCurrent(request, currentMode) {
      return Boolean(request)
        && request.generation === generation
        && request.mode === currentMode;
    },
  };
}

export function parseScanQuantity(rawValue) {
  const value = String(rawValue ?? '').trim();
  if (!/^\d+$/.test(value)) return null;
  const quantity = Number(value);
  return Number.isSafeInteger(quantity) && quantity > 0 ? quantity : null;
}

export function buildMovementPayload(action, quantity, idempotencyKey, options = {}) {
  if (!['receive', 'consume', 'initialize'].includes(action)) throw new TypeError('Invalid movement action');
  const validQuantity = Number.isSafeInteger(quantity)
    && (action === 'initialize' ? quantity >= 0 : quantity > 0);
  if (!validQuantity) throw new TypeError(action === 'initialize'
    ? 'Initial quantity must be a non-negative whole package count'
    : 'Quantity must be a positive whole package count');
  if (typeof idempotencyKey !== 'string' || !idempotencyKey.trim()) throw new TypeError('Idempotency key is required');
  const payload = {
    action,
    quantity,
    source: options.source || 'manual',
    idempotency_key: idempotencyKey.trim(),
  };
  if (action === 'initialize') {
    if (!['inventory', 'exact'].includes(options.trackingMode || 'exact')) throw new TypeError('Initial stock needs a numeric tracking mode');
    payload.confirm_initial_stock = true;
    payload.tracking_mode = options.trackingMode || 'exact';
  }
  return payload;
}
