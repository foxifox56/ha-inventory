export async function lookupBarcodeValue(rawBarcode, lookup, handlers) {
  const barcode = String(rawBarcode ?? '').trim();
  if (!barcode) return { outcome: 'empty' };

  handlers.pending?.(barcode);
  try {
    const result = await lookup(barcode);
    if (result?.status === 'local' && result.item) {
      handlers.found(result.item);
      return { outcome: 'found', item: result.item };
    }
    if (result?.status === 'identified' && result.product) {
      handlers.identified?.(barcode, result.product);
      return { outcome: 'identified', barcode, product: result.product };
    }
    if (result?.status === 'not_found') {
      handlers.missing(barcode);
      return { outcome: 'missing', barcode };
    }
    throw new Error('Die Produktsuche lieferte ein unbekanntes Antwortformat.');
  } catch (error) {
    handlers.failed(error, barcode);
    return { outcome: 'failed', error };
  } finally {
    handlers.settled?.(barcode);
  }
}
