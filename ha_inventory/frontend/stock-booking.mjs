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

export function buildMovementPayload(action, quantity, idempotencyKey, options = {}) {
  if (!['receive', 'consume', 'initialize'].includes(action)) throw new TypeError('Invalid movement action');
  if (!Number.isInteger(quantity) || quantity <= 0) throw new TypeError('Quantity must be a positive whole package count');
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
