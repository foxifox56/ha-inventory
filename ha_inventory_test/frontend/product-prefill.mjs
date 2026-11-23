// Keep product metadata as editable form suggestions; this module never saves it.
export function productPrefillValues(barcode, product = {}) {
  return {
    barcode: String(barcode ?? ''),
    name: product.name || '',
    brand: product.brand || '',
    product_size: product.product_size || '',
    category: product.category || 'Sonstiges',
    image_url: product.image_url || '',
    image_license: product.image_license || '',
    data_source: product.data_source || '',
    source_url: product.source_url || '',
  };
}
