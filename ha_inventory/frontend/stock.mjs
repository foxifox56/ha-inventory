export function formatQuantity(value) {
  return new Intl.NumberFormat('de-DE', { maximumFractionDigits: 2 }).format(value);
}

export function trackingModeLabel(mode) {
  return {
    simple: 'Einfacher Vorrat',
    inventory: 'Inventar · geschätzt',
    exact: 'Exakter Bestand',
  }[mode] || 'Einfacher Vorrat';
}

export function simpleStockStatus(status) {
  return ['unknown', 'present', 'out_of_stock'].includes(status) ? status : 'unknown';
}

export function stockLabel(item) {
  if (item.tracking_mode === 'simple') {
    return {
      unknown: 'Bestand unbekannt',
      present: 'Vorhanden',
      out_of_stock: 'Nicht vorhanden',
    }[item.stock_status] || 'Bestand unbekannt';
  }
  if (item.quantity === null || item.quantity === undefined) return 'Bestand unbekannt';
  const quantity = `${formatQuantity(item.quantity)} ${item.unit || 'Stück'}`;
  return item.tracking_mode === 'inventory' ? `ca. ${quantity}` : quantity;
}

export function stockDetail(item) {
  if (item.tracking_mode === 'simple') return stockLabel(item);
  const label = stockLabel(item);
  if (item.stock_status === 'unknown') return label;
  return item.tracking_mode === 'inventory'
    ? `${label} · manuell geschätzter Richtwert`
    : `${label} · manuell eingetragener Zählstand`;
}

export function isLowStock(item) {
  return item.tracking_mode !== 'simple'
    && item.quantity !== null
    && item.quantity !== undefined
    && item.minimum_quantity > 0
    && item.quantity <= item.minimum_quantity;
}
