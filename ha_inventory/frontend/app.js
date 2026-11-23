import { isLowStock, simpleStockStatus, stockDetail, stockLabel, trackingModeLabel } from './stock.mjs';
import { lookupBarcodeValue } from './barcode-lookup.mjs';
import { groupByLocation, filterItems, MOBILE_VIEWS } from './mobile-navigation.mjs';
import { startZXingScanner } from './zxing-scanner.mjs';
import { BrowserMultiFormatReader } from './vendor/zxing-browser.mjs';

const API = new URL('api/v1/', document.baseURI).toString();
const $ = (selector) => document.querySelector(selector);
const itemDialog = $('#item-dialog');
const detailDialog = $('#detail-dialog');
const scanDialog = $('#scan-dialog');
const form = $('#item-form');
let items = [];
let activeCategory = '';
let activeLocation = '';
let activeView = 'home';
let scanReturnView = 'home';
let toastTimeout;
let scannerControls;
let scannerBusy = false;
let activeDetailItem;
let writeToken = '';

async function acquireWriteSession() {
  const response = await fetch(new URL('write-session', API), { cache: 'no-store' });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body.write_token) throw new Error(body.error || 'Schreibsitzung konnte nicht geöffnet werden.');
  writeToken = body.write_token;
}

async function api(path, options = {}, refreshedWriteSession = false) {
  const method = (options.method || 'GET').toUpperCase();
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !writeToken) await acquireWriteSession();
  const response = await fetch(new URL(path, API), {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(method !== 'GET' && writeToken ? { 'X-HA-Inventory-Write-Token': writeToken } : {}),
      ...(options.headers || {}),
    },
  });
  if (response.status === 403 && !refreshedWriteSession && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    await acquireWriteSession();
    return api(path, options, true);
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body.error || 'Die Anfrage ist fehlgeschlagen.');
    error.status = response.status;
    error.field = body.field;
    throw error;
  }
  return body;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('visible');
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => toast.classList.remove('visible'), 3000);
}

function iconFor(category) {
  const icons = { Lebensmittel: '◉', Werkzeuge: '⌁', Haushalt: '⌂', Sonstiges: '▦' };
  return icons[category] || '▦';
}

function render() {
  $('#stat-items').textContent = items.length;
  $('#stat-low').textContent = items.filter(isLowStock).length;
  $('#stat-locations').textContent = new Set(items.map((item) => item.location.trim()).filter(Boolean)).size;
  renderLocations();
  renderFilters();
}

function renderLocations() {
  const groups = groupByLocation(items);
  $('#location-list').innerHTML = groups.map((group) => `<button class="location-card" type="button" data-location="${escapeHtml(group.location)}">
    <span class="location-name"><span aria-hidden="true">⌖</span><span>${escapeHtml(group.location)}</span></span>
    <span class="location-count">${group.count} ${group.count === 1 ? 'Artikel' : 'Artikel'} ›</span>
  </button>`).join('');
  $('#locations-empty').hidden = groups.length !== 0;
}

function renderFilters() {
  const categories = [...new Set(items.map((item) => item.category))].sort((a, b) => a.localeCompare(b, 'de'));
  const available = ['', ...categories];
  if (!available.includes(activeCategory)) activeCategory = '';
  $('#category-filters').innerHTML = [
    `<button class="filter-chip ${activeCategory === '' ? 'active' : ''}" data-category="" type="button">Alle</button>`,
    ...categories.map((category) => `<button class="filter-chip ${activeCategory === category ? 'active' : ''}" data-category="${escapeHtml(category)}" type="button">${escapeHtml(category)}</button>`),
  ].join('');
  const filtered = filterItems(items, {
    query: $('#search-input').value,
    category: activeCategory,
    location: activeLocation,
  });
  const list = $('#item-list');
  list.innerHTML = filtered.map((item) => renderItem(item)).join('');
  list.hidden = filtered.length === 0;
  $('#empty-state').hidden = filtered.length !== 0;
  $('#empty-title').textContent = items.length ? 'Keine Treffer gefunden' : 'Dein Lager ist noch leer';
  $('#empty-copy').textContent = items.length
    ? 'Ändere den Suchbegriff oder wähle eine andere Kategorie.'
    : 'Lege deinen ersten Artikel an oder scanne seinen Barcode.';
  $('#result-count').textContent = items.length === 0
    ? 'Noch keine Artikel erfasst'
    : `${filtered.length} von ${items.length} Artikeln angezeigt`;
  const activeLocationLabel = $('#active-location');
  activeLocationLabel.hidden = !activeLocation;
  activeLocationLabel.innerHTML = activeLocation
    ? `${activeLocation === 'Ohne Lagerort' ? 'Ohne Lagerort' : `Lagerort: ${escapeHtml(activeLocation)}`} <button class="clear-location" type="button" data-clear-location>Alle Lagerorte</button>`
    : '';
}

function renderItem(item) {
  const isLow = isLowStock(item);
  const isEmpty = item.tracking_mode === 'simple' && item.stock_status === 'out_of_stock';
  return `<article class="item-row">
    <div class="item-main">
      <span class="item-symbol" aria-hidden="true">${iconFor(item.category)}</span>
      <div class="item-copy">
        <div class="item-name">${escapeHtml(item.name)}</div>
        <div class="item-barcode">${item.barcode ? `▤ ${escapeHtml(item.barcode)}` : 'Kein Barcode'}</div>
      </div>
    </div>
    <span class="item-category">${escapeHtml(item.category)}</span>
    <span class="item-quantity ${isLow || isEmpty ? 'low-stock' : ''}">${escapeHtml(stockLabel(item))}${isLow ? ' · knapp' : ''}</span>
    <span class="item-location">${item.location ? `<span class="location-value">⌖ ${escapeHtml(item.location)}</span>` : '<span class="location-value">Ohne Lagerort</span>'}</span>
    <div class="row-actions">
      <button class="icon-button view-item" type="button" data-id="${item.id}" aria-label="${escapeHtml(item.name)} ansehen">◉</button>
      <button class="icon-button edit-item" type="button" data-id="${item.id}" aria-label="${escapeHtml(item.name)} bearbeiten">✎</button>
      <button class="icon-button delete-item" type="button" data-id="${item.id}" aria-label="${escapeHtml(item.name)} löschen">×</button>
    </div>
  </article>`;
}

async function loadItems() {
  try {
    const result = await api('items');
    items = result.items;
    render();
  } catch (error) {
    showToast(`Verbindung fehlgeschlagen: ${error.message}`);
  }
}

function resetForm() {
  form.reset();
  $('#item-id').value = '';
  $('#item-tracking-mode').value = 'simple';
  $('#item-stock-status').value = 'unknown';
  $('#item-quantity').value = '';
  $('#item-unit').value = 'Stück';
  $('#item-minimum').value = '0';
  syncTrackingFields();
  $('#form-title').textContent = 'Neuer Artikel';
  $('#form-error').hidden = true;
  $('#form-error').textContent = '';
}

function openNewItem(barcode = '') {
  resetForm();
  $('#item-barcode').value = barcode;
  itemDialog.showModal();
  $('#item-name').focus();
}

function openEditItem(item) {
  resetForm();
  $('#item-id').value = item.id;
  $('#item-name').value = item.name;
  $('#item-barcode').value = item.barcode || '';
  $('#item-category').value = item.category;
  $('#item-location').value = item.location;
  $('#item-tracking-mode').value = item.tracking_mode;
  $('#item-stock-status').value = simpleStockStatus(item.stock_status);
  $('#item-quantity').value = item.quantity ?? '';
  $('#item-unit').value = item.unit;
  $('#item-minimum').value = item.minimum_quantity;
  $('#item-notes').value = item.notes;
  syncTrackingFields();
  $('#form-title').textContent = 'Artikel bearbeiten';
  itemDialog.showModal();
  $('#item-name').focus();
}

function syncTrackingFields() {
  const simple = $('#item-tracking-mode').value === 'simple';
  $('#simple-stock-field').hidden = !simple;
  $('#numeric-stock-fields').hidden = simple;
  if (simple) {
    $('#item-stock-status').value = simpleStockStatus($('#item-stock-status').value);
    $('#item-quantity').value = '';
  }
}

function openDetailItem(item) {
  activeDetailItem = item;
  $('#detail-name').textContent = item.name;
  $('#detail-stock').textContent = stockDetail(item);
  $('#detail-mode').textContent = trackingModeLabel(item.tracking_mode);
  $('#detail-category').textContent = item.category || 'Sonstiges';
  $('#detail-location').textContent = item.location || 'Kein Lagerort hinterlegt';
  $('#detail-barcode').textContent = item.barcode || 'Kein Barcode hinterlegt';
  $('#detail-notes').textContent = item.notes || '';
  $('#detail-notes-wrap').hidden = !item.notes;
  detailDialog.showModal();
}

function closeScanDialog() {
  if (scanDialog.open) scanDialog.close();
  stopCamera();
  setActiveTab(scanReturnView);
}

async function lookupBarcode(rawBarcode) {
  const result = await lookupBarcodeValue(rawBarcode, async (barcode) => {
    const { item } = await api(`items/by-barcode/${encodeURIComponent(barcode)}`);
    return item;
  }, {
    found: (item) => {
      closeScanDialog();
      openDetailItem(item);
    },
    missing: (barcode) => {
      closeScanDialog();
      openNewItem(barcode);
    },
    failed: (error) => showToast(error.message),
  });
  if (result.outcome === 'empty') {
    $('#scan-input').focus();
  }
}

async function startCamera() {
  const status = $('#camera-status');
  const wrap = $('#camera-wrap');
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    status.textContent = 'Die Kamera ist nur auf einer sicheren HTTPS-Seite verfügbar. Du kannst den Barcode unten eingeben.';
    status.hidden = false;
    return;
  }
  $('#camera-button').disabled = true;
  $('#camera-button').textContent = 'Kamera wird geöffnet …';
  try {
    const video = $('#camera-video');
    wrap.hidden = false;
    status.hidden = true;
    scannerBusy = false;
    const reader = new BrowserMultiFormatReader();
    scannerControls = await startZXingScanner(reader, video, (barcode) => {
      if (scannerBusy) return;
      scannerBusy = true;
      void lookupBarcode(barcode);
    }, (error) => {
      status.textContent = error.name === 'NotAllowedError'
        ? 'Kamerazugriff verweigert. Erlaube den Zugriff im Browser oder gib den Barcode ein.'
        : 'Der Barcode konnte noch nicht gelesen werden. Richte die Kamera auf den Code.';
      status.hidden = false;
    });
    if (!scanDialog.open) stopCamera();
  } catch (error) {
    status.textContent = error.name === 'NotAllowedError'
      ? 'Kamerazugriff verweigert. Erlaube den Zugriff im Browser oder gib den Barcode ein.'
      : 'Kamera konnte nicht geöffnet werden. Gib den Barcode unten ein.';
    status.hidden = false;
  } finally {
    $('#camera-button').disabled = false;
    $('#camera-button').textContent = 'Kamera erneut öffnen';
  }
}

function stopCamera() {
  scannerControls?.stop();
  scannerControls = undefined;
  scannerBusy = false;
  const video = $('#camera-video');
  video.pause();
  video.srcObject = null;
  $('#camera-wrap').hidden = true;
}

function setView(view, { focusSearch = false } = {}) {
  if (!MOBILE_VIEWS.includes(view)) return;
  if (view === 'scanner') {
    scanReturnView = activeView;
    $('#scan-input').value = '';
    $('#camera-status').hidden = true;
    scanDialog.showModal();
    setActiveTab('scanner');
    setTimeout(() => $('#camera-button').hidden ? $('#scan-input').focus() : $('#camera-button').focus(), 60);
    return;
  }
  if (view === 'home') {
    activeLocation = '';
    activeCategory = '';
    $('#search-input').value = '';
  }
  activeView = view;
  document.querySelector('main').dataset.mobileView = view;
  setActiveTab(view);
  if (focusSearch || view === 'search') setTimeout(() => $('#search-input').focus(), 80);
  renderFilters();
}

function setActiveTab(view) {
  document.querySelectorAll('.nav-tab').forEach((tab) => {
    const active = tab.dataset.view === view;
    tab.classList.toggle('is-active', active);
    if (active) tab.setAttribute('aria-current', 'page');
    else tab.removeAttribute('aria-current');
  });
}

$('#add-button').addEventListener('click', () => openNewItem());
$('#empty-add-button').addEventListener('click', () => openNewItem());
$('#scan-button').addEventListener('click', () => setView('scanner'));
document.querySelector('.mobile-nav').addEventListener('click', (event) => {
  const tab = event.target.closest('[data-view]');
  if (tab) setView(tab.dataset.view);
});
$('#location-list').addEventListener('click', (event) => {
  const button = event.target.closest('[data-location]');
  if (!button) return;
  activeLocation = button.dataset.location;
  if (window.matchMedia('(max-width: 759px)').matches) setView('search');
  else renderFilters();
});
$('#active-location').addEventListener('click', (event) => {
  if (!event.target.closest('[data-clear-location]')) return;
  activeLocation = '';
  renderFilters();
});
$('#close-item-dialog').addEventListener('click', () => itemDialog.close());
$('#cancel-item').addEventListener('click', () => itemDialog.close());
$('#close-detail-dialog').addEventListener('click', () => detailDialog.close());
$('#close-detail-button').addEventListener('click', () => detailDialog.close());
$('#detail-edit-button').addEventListener('click', () => {
  if (!activeDetailItem) return;
  detailDialog.close();
  openEditItem(activeDetailItem);
});
$('#close-scan-dialog').addEventListener('click', closeScanDialog);
$('#camera-button').addEventListener('click', startCamera);
$('#lookup-button').addEventListener('click', () => lookupBarcode($('#scan-input').value));
$('#scan-input').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    lookupBarcode($('#scan-input').value);
  }
});
$('#search-input').addEventListener('input', renderFilters);
$('#item-tracking-mode').addEventListener('change', syncTrackingFields);
$('#category-filters').addEventListener('click', (event) => {
  const button = event.target.closest('[data-category]');
  if (!button) return;
  activeCategory = button.dataset.category;
  renderFilters();
});
$('#item-list').addEventListener('click', async (event) => {
  const editButton = event.target.closest('.edit-item');
  const viewButton = event.target.closest('.view-item');
  const deleteButton = event.target.closest('.delete-item');
  if (viewButton) {
    const item = items.find((entry) => entry.id === Number(viewButton.dataset.id));
    if (item) openDetailItem(item);
  }
  if (editButton) {
    const item = items.find((entry) => entry.id === Number(editButton.dataset.id));
    if (item) openEditItem(item);
  }
  if (deleteButton) {
    const item = items.find((entry) => entry.id === Number(deleteButton.dataset.id));
    if (!item || !window.confirm(`„${item.name}“ wirklich aus dem Lager entfernen?`)) return;
    try {
      await api(`items/${item.id}`, { method: 'DELETE' });
      showToast(`${item.name} wurde gelöscht.`);
      await loadItems();
    } catch (error) {
      showToast(error.message);
    }
  }
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const id = $('#item-id').value;
  const payload = {
    name: $('#item-name').value,
    barcode: $('#item-barcode').value,
    category: $('#item-category').value || 'Sonstiges',
    location: $('#item-location').value,
    tracking_mode: $('#item-tracking-mode').value,
    stock_status: $('#item-tracking-mode').value === 'simple'
      ? $('#item-stock-status').value
      : ($('#item-quantity').value.trim() ? 'known' : 'unknown'),
    quantity: $('#item-tracking-mode').value === 'simple'
      ? null
      : ($('#item-quantity').value.trim() ? Number($('#item-quantity').value) : null),
    unit: $('#item-unit').value || 'Stück',
    minimum_quantity: Number($('#item-minimum').value),
    notes: $('#item-notes').value,
  };
  try {
    await api(id ? `items/${id}` : 'items', {
      method: id ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });
    itemDialog.close();
    showToast(id ? 'Artikel aktualisiert.' : 'Artikel hinzugefügt.');
    await loadItems();
  } catch (error) {
    $('#form-error').textContent = error.message;
    $('#form-error').hidden = false;
    if (error.field) document.querySelector(`[name="${error.field}"]`)?.focus();
  }
});

scanDialog.addEventListener('close', stopCamera);
scanDialog.addEventListener('close', () => setActiveTab(scanReturnView));
document.addEventListener('keydown', (event) => {
  if (event.key === '/' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
    event.preventDefault();
    $('#search-input').focus();
  }
  if (event.key === 'Escape' && scanDialog.open) stopCamera();
});

if (window.isSecureContext && navigator.mediaDevices?.getUserMedia) {
  $('#camera-button').hidden = false;
}

acquireWriteSession().catch((error) => showToast(`Schreibzugriff: ${error.message}`));
loadItems();
