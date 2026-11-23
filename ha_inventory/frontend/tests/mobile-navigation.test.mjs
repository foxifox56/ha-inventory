import test from 'node:test';
import assert from 'node:assert/strict';
import { filterItems, groupByLocation, MOBILE_VIEWS, normalizeLocation } from '../mobile-navigation.mjs';

const items = [
  { id: 1, name: 'Olivenöl', barcode: '00123', category: 'Lebensmittel', location: 'Speisekammer' },
  { id: 2, name: 'Hammer', barcode: '', category: 'Werkzeuge', location: 'Werkstatt' },
  { id: 3, name: 'Lappen', barcode: '9', category: 'Haushalt', location: '' },
];

test('mobile navigation exposes the requested destinations and receipt entry', () => {
  assert.deepEqual(MOBILE_VIEWS, ['home', 'search', 'scanner', 'locations', 'receipts']);
});

test('location grouping sorts locations and keeps unassigned items visible', () => {
  assert.equal(normalizeLocation('  '), 'Ohne Lagerort');
  assert.deepEqual(groupByLocation(items).map(({ location, count }) => [location, count]), [
    ['Ohne Lagerort', 1],
    ['Speisekammer', 1],
    ['Werkstatt', 1],
  ]);
});

test('search combines text, category, and selected location filters', () => {
  assert.deepEqual(filterItems(items, { query: 'OLIVEN', category: 'Lebensmittel' }).map((item) => item.id), [1]);
  assert.deepEqual(filterItems(items, { location: 'Werkstatt' }).map((item) => item.name), ['Hammer']);
  assert.deepEqual(filterItems(items, { query: '00123' }).map((item) => item.name), ['Olivenöl']);
  assert.deepEqual(filterItems(items, { location: 'Ohne Lagerort' }).map((item) => item.id), [3]);
});
