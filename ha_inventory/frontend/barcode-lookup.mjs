export async function lookupBarcodeValue(rawBarcode, lookup, handlers) {
  const barcode = String(rawBarcode ?? '').trim();
  if (!barcode) return { outcome: 'empty' };

  try {
    const item = await lookup(barcode);
    handlers.found(item);
    return { outcome: 'found', item };
  } catch (error) {
    if (error.status === 404) {
      handlers.missing(barcode);
      return { outcome: 'missing', barcode };
    }
    handlers.failed(error);
    return { outcome: 'failed', error };
  }
}
