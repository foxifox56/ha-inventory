export const MOBILE_VIEWS = Object.freeze(['home', 'search', 'scanner', 'locations', 'receipts']);

export function normalizeLocation(location) {
  const value = String(location ?? '').trim();
  return value || 'Ohne Lagerort';
}

export function groupByLocation(items) {
  const groups = new Map();
  for (const item of items) {
    const location = normalizeLocation(item.location);
    if (!groups.has(location)) groups.set(location, []);
    groups.get(location).push(item);
  }
  return [...groups.entries()]
    .sort(([left], [right]) => left.localeCompare(right, 'de'))
    .map(([location, entries]) => ({ location, items: entries, count: entries.length }));
}

export function filterItems(items, { query = '', category = '', location = '' } = {}) {
  const normalizedQuery = String(query).trim().toLocaleLowerCase('de');
  return items.filter((item) => {
    const categoryMatches = !category || item.category === category;
    const itemLocation = normalizeLocation(item.location);
    const locationMatches = !location || itemLocation === location;
    const text = `${item.name ?? ''} ${item.barcode ?? ''} ${item.location ?? ''}`.toLocaleLowerCase('de');
    return categoryMatches && locationMatches && (!normalizedQuery || text.includes(normalizedQuery));
  });
}
