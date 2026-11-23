function abortError() {
  const error = new Error('Produktsuche abgebrochen.');
  error.name = 'AbortError';
  return error;
}

function waitUnlessAborted(milliseconds, signal) {
  if (signal?.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const finish = () => {
      signal?.removeEventListener('abort', cancel);
      resolve();
    };
    const cancel = () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', cancel);
      reject(abortError());
    };
    const timer = setTimeout(finish, milliseconds);
    signal?.addEventListener('abort', cancel, { once: true });
  });
}

/**
 * Resolve a barcode without creating or changing an inventory item. Open Facts
 * rate-limit responses are retried a bounded number of times and the wait can
 * be cancelled when the user chooses manual entry.
 */
export async function lookupBarcodeValue(rawBarcode, lookup, handlers, options = {}) {
  const barcode = String(rawBarcode ?? '').trim();
  if (!barcode) return { outcome: 'empty' };

  const signal = options.signal;
  const wait = options.wait || waitUnlessAborted;
  const maxRetries = options.maxRetries ?? 2;
  const maxWaitMs = options.maxWaitMs ?? 12000;
  let retries = 0;
  let plannedWaitMs = 0;

  handlers.pending?.(barcode);
  try {
    while (true) {
      if (signal?.aborted) {
        handlers.cancelled?.(barcode);
        return { outcome: 'cancelled', barcode };
      }

      let result;
      try {
        result = await lookup(barcode, { signal });
      } catch (error) {
        if (signal?.aborted || error?.name === 'AbortError') {
          handlers.cancelled?.(barcode);
          return { outcome: 'cancelled', barcode };
        }

        const retryAfterSeconds = Number(error?.retryAfterSeconds);
        const delayMs = Math.ceil(retryAfterSeconds * 1000);
        const waitMs = delayMs + 50;
        if (
          error?.code === 'product_lookup_rate_limited'
          && Number.isFinite(delayMs)
          && delayMs > 0
          && retries < maxRetries
          && plannedWaitMs + waitMs <= maxWaitMs
        ) {
          retries += 1;
          plannedWaitMs += waitMs;
          handlers.waiting?.(barcode, retryAfterSeconds, retries);
          try {
            await wait(waitMs, signal);
          } catch (waitError) {
            if (signal?.aborted || waitError?.name === 'AbortError') {
              handlers.cancelled?.(barcode);
              return { outcome: 'cancelled', barcode };
            }
            handlers.failed(waitError, barcode);
            return { outcome: 'failed', error: waitError, barcode };
          }
          continue;
        }

        handlers.failed(error, barcode);
        return { outcome: 'failed', error, barcode };
      }

      if (result?.status === 'local' && result.item) {
        await handlers.found(result.item);
        return { outcome: 'found', item: result.item };
      }
      if (result?.status === 'identified' && result.product) {
        await handlers.identified?.(barcode, result.product);
        return { outcome: 'identified', barcode, product: result.product };
      }
      if (result?.status === 'not_found') {
        await handlers.missing(barcode);
        return { outcome: 'missing', barcode };
      }
      const error = new Error('Die Produktsuche lieferte ein unbekanntes Antwortformat.');
      handlers.failed(error, barcode);
      return { outcome: 'failed', error, barcode };
    }
  } finally {
    handlers.settled?.(barcode);
  }
}
