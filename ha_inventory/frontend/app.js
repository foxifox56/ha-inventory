import { isLowStock, simpleStockStatus, stockDetail, stockLabel, trackingModeLabel } from './stock.mjs';
import { lookupBarcodeValue } from './barcode-lookup.mjs';
import { groupByLocation, filterItems, MOBILE_VIEWS } from './mobile-navigation.mjs';
import { startZXingScanner } from './zxing-scanner.mjs';
import { BrowserMultiFormatReader } from './vendor/zxing-browser.mjs';
import { createApiClient } from './api-client.mjs';
import { productPrefillValues } from './product-prefill.mjs';
import { bookingForScan, buildMovementPayload, createIdempotencyKey, createScanDeduplicator } from './stock-booking.mjs';

const API = new URL('api/v1/', document.baseURI).toString();
const apiClient = createApiClient((...args) => window.fetch(...args), API);
const api = (...args) => apiClient.request(...args);
const $ = (selector) => document.querySelector(selector);
const itemDialog = $('#item-dialog');
const detailDialog = $('#detail-dialog');
const scanDialog = $('#scan-dialog');
const bookingDialog = $('#booking-dialog');
const bookingForm = $('#booking-form');
const historyDialog = $('#history-dialog');
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
let barcodeLookupInProgress = false;
let lookupAbortController;
let lookupFailed = false;
let itemSaveInProgress = false;
let bookingInProgress = false;
let activeBookingItem;
let activeBookingAction = 'receive';
let activeBookingSource = 'manual';
let pendingCreateBooking = false;
const duplicateScan = createScanDeduplicator(1200);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.remove('has-action');
  toast.classList.add('visible');
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => toast.classList.remove('visible'), 3000);
}

function showUndoToast(item, movement, message) {
  const toast = $('#toast');
  toast.innerHTML = `<span>${escapeHtml(message)}</span><button class="toast-action" type="button" data-undo-movement="${movement.id}" data-item-id="${item.id}">Rückgängig</button>`;
  toast.classList.add('visible', 'has-action');
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => toast.classList.remove('visible', 'has-action'), 8000);
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
        ${item.brand ? `<div class="item-brand">${escapeHtml(item.brand)}</div>` : ''}
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
    if (activeDetailItem) {
      activeDetailItem = items.find((item) => item.id === activeDetailItem.id) || activeDetailItem;
      if (detailDialog.open) refreshDetailItem();
    }
    render();
  } catch (error) {
    showToast(`Verbindung fehlgeschlagen: ${error.message}`);
  }
}

function resetForm() {
  form.reset();
  $('#item-id').value = '';
  $('#item-data-source').value = '';
  $('#item-source-url').value = '';
  $('#item-image-license').value = '';
  renderProductAttribution('', '', '', '');
  $('#item-tracking-mode').value = 'simple';
  $('#item-tracking-mode').disabled = false;
  $('#item-stock-status').value = 'unknown';
  $('#item-stock-status').disabled = false;
  $('#item-quantity').value = '';
  $('#item-quantity').disabled = false;
  $('#saved-stock-note').hidden = true;
  $('#item-unit').value = 'Stück';
  $('#item-minimum').value = '0';
  syncTrackingFields();
  $('#form-title').textContent = 'Neuer Artikel';
  $('#form-error').hidden = true;
  $('#form-error').textContent = '';
}

function openNewItem(barcode = '', product = null) {
  resetForm();
  $('#create-stock-note').hidden = !pendingCreateBooking;
  if (product) {
    const values = productPrefillValues(barcode, product);
    $('#item-barcode').value = values.barcode;
    $('#item-name').value = values.name;
    $('#item-brand').value = values.brand;
    $('#item-product-size').value = values.product_size;
    $('#item-category').value = values.category;
    $('#item-image-url').value = values.image_url;
    $('#item-data-source').value = values.data_source;
    $('#item-source-url').value = values.source_url;
    $('#item-image-license').value = values.image_license;
    renderProductAttribution(
      values.data_source, values.source_url, values.image_url, values.image_license,
    );
  } else $('#item-barcode').value = barcode;
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
  $('#item-tracking-mode').disabled = true;
  $('#item-stock-status').value = simpleStockStatus(item.stock_status);
  $('#item-stock-status').disabled = true;
  $('#item-quantity').value = item.quantity ?? '';
  $('#item-quantity').disabled = true;
  $('#saved-stock-note').hidden = false;
  $('#item-unit').value = item.unit;
  $('#item-minimum').value = item.minimum_quantity;
  $('#item-notes').value = item.notes;
  $('#item-brand').value = item.brand || '';
  $('#item-product-size').value = item.product_size || '';
  $('#item-image-url').value = item.image_url || '';
  $('#item-data-source').value = item.data_source || '';
  $('#item-source-url').value = item.source_url || '';
  $('#item-image-license').value = item.image_license || '';
  renderProductAttribution(
    item.data_source || '', item.source_url || '', item.image_url || '', item.image_license || '',
  );
  syncTrackingFields();
  $('#form-title').textContent = 'Artikel bearbeiten';
  itemDialog.showModal();
  $('#item-name').focus();
}

function isOpenFactsImage(value) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'https:' && [
      'openfoodfacts.org', 'openbeautyfacts.org',
      'openpetfoodfacts.org', 'openproductsfacts.org',
    ].some((domain) => parsed.hostname === domain || parsed.hostname.endsWith(`.${domain}`));
  } catch {
    return false;
  }
}

function renderProductAttribution(source, sourceUrl, imageUrl, imageLicense = '') {
  const formContainer = $('#product-attribution');
  const preview = $('#product-preview');
  if (!formContainer || !preview) return;
  if (isOpenFactsImage(imageUrl)) {
    preview.src = imageUrl;
    preview.hidden = false;
  } else {
    preview.removeAttribute('src');
    preview.hidden = true;
  }
  const sourceLink = $('#product-source-link');
  if (source && sourceUrl) {
    sourceLink.textContent = `${source}${!preview.hidden && imageLicense ? ` · Bild: ${imageLicense}` : ''}`;
    sourceLink.href = sourceUrl;
    formContainer.hidden = false;
  } else {
    sourceLink.textContent = '';
    sourceLink.removeAttribute('href');
    formContainer.hidden = preview.hidden;
  }

  const detailContainer = $('#detail-product-media');
  const detailImage = $('#detail-product-image');
  if (!detailContainer || !detailImage) return;
  if (isOpenFactsImage(imageUrl)) {
    detailImage.src = imageUrl;
    detailImage.hidden = false;
  } else {
    detailImage.removeAttribute('src');
    detailImage.hidden = true;
  }
  const detailSource = $('#detail-product-source');
  if (source && sourceUrl) {
    detailSource.textContent = `${source}${!detailImage.hidden && imageLicense ? ` · Bild: ${imageLicense}` : ''}`;
    detailSource.href = sourceUrl;
    detailContainer.hidden = false;
  } else {
    detailSource.textContent = '';
    detailSource.removeAttribute('href');
    detailContainer.hidden = detailImage.hidden;
  }
}

$('#item-image-url').addEventListener('input', () => {
  renderProductAttribution(
    $('#item-data-source').value,
    $('#item-source-url').value,
    $('#item-image-url').value.trim(),
    $('#item-image-license').value,
  );
});

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
  refreshDetailItem();
  detailDialog.showModal();
}

function refreshDetailItem() {
  const item = activeDetailItem;
  if (!item) return;
  $('#detail-name').textContent = item.name;
  $('#detail-stock').textContent = stockDetail(item);
  $('#detail-mode').textContent = trackingModeLabel(item.tracking_mode);
  $('#detail-category').textContent = item.category || 'Sonstiges';
  $('#detail-location').textContent = item.location || 'Kein Lagerort hinterlegt';
  $('#detail-barcode').textContent = item.barcode || 'Kein Barcode hinterlegt';
  $('#detail-brand').textContent = item.brand || 'Keine Marke hinterlegt';
  $('#detail-product-size').textContent = item.product_size || 'Keine Packungsgröße hinterlegt';
  $('#detail-notes').textContent = item.notes || '';
  $('#detail-notes-wrap').hidden = !item.notes;
  renderProductAttribution(
    item.data_source || '', item.source_url || '', item.image_url || '', item.image_license || '',
  );
}

function hasKnownCount(item) {
  return item.tracking_mode !== 'simple'
    && item.quantity !== null && item.quantity !== undefined
    && item.stock_status === 'known';
}

function openBookingDialog(item, requestedAction = 'receive', source = 'manual', quantity = 1) {
  if (!item) return;
  const decision = bookingForScan(requestedAction === 'consume' ? 'consume' : 'receive', item);
  const action = requestedAction === 'initialize' ? 'initialize' : decision.action;
  if (action === 'unavailable') {
    showToast('Der Zahlenbestand ist unbekannt. Lege zuerst über „Einlagern“ einen Startbestand fest.');
    return;
  }
  activeBookingItem = item;
  activeBookingAction = action;
  activeBookingSource = source;
  $('#booking-title').textContent = action === 'initialize'
    ? 'Startbestand festlegen'
    : (action === 'consume' ? 'Verbrauchen' : 'Einlagern');
  $('#booking-item-name').textContent = item.name;
  $('#booking-quantity').value = String(Number.isInteger(quantity) && quantity > 0 ? quantity : 1);
  $('#initial-stock-fields').hidden = action !== 'initialize';
  $('#confirm-initial-stock').checked = false;
  $('#initial-tracking-mode').value = item.tracking_mode === 'inventory' ? 'inventory' : 'exact';
  $('#booking-stock-note').textContent = action === 'initialize'
    ? 'Für diesen Artikel ist noch keine Stückzahl bekannt. Die Menge wird erst nach deiner ausdrücklichen Bestätigung als Startbestand gesetzt.'
    : (action === 'consume'
      ? `Aktueller Bestand: ${stockLabel(item)}. Verbrauch wird erst nach Bestätigung gebucht.`
      : `Aktueller Bestand: ${stockLabel(item)}. Die Packungsgröße des Produkts ändert die Anzahl nicht.`);
  $('#booking-submit').textContent = action === 'initialize'
    ? 'Startbestand bestätigen'
    : (action === 'consume' ? 'Verbrauch bestätigen' : 'Einlagern bestätigen');
  $('#booking-error').hidden = true;
  if (!bookingDialog.open) bookingDialog.showModal();
}

async function writeMovement(item, action, quantity, source, { initialMode } = {}) {
  const payload = buildMovementPayload(action, quantity, createIdempotencyKey(), {
    source,
    trackingMode: initialMode || 'exact',
  });
  const result = await api(`items/${item.id}/movements`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return result.movement;
}

function movementMessage(item, movement) {
  if (movement.action === 'undo') return `Buchung für ${item.name} wurde rückgängig gemacht.`;
  const amount = `${Math.abs(movement.delta_quantity)} ${Math.abs(movement.delta_quantity) === 1 ? 'Packung' : 'Packungen'}`;
  return movement.action === 'consume'
    ? `${amount} ${item.name} verbraucht.`
    : `${amount} ${item.name} eingelagert.`;
}

async function consumeFromScan(item, quantity) {
  if (!hasKnownCount(item)) {
    $('#camera-status').textContent = `${item.name}: Der Zahlenbestand ist unbekannt. Es wurde nichts abgezogen. Öffne „Einlagern“, um einen Startbestand festzulegen.`;
    $('#camera-status').hidden = false;
    return;
  }
  try {
    const movement = await writeMovement(item, 'consume', quantity, 'barcode');
    await loadItems();
    const current = items.find((entry) => entry.id === item.id) || item;
    $('#camera-status').textContent = movementMessage(item, movement);
    $('#camera-status').hidden = false;
    showUndoToast(current, movement, movementMessage(item, movement));
  } catch (error) {
    $('#camera-status').textContent = `Nicht gebucht: ${error.message}`;
    $('#camera-status').hidden = false;
  }
}

async function openHistory(item) {
  if (!item) return;
  $('#history-title').textContent = `${item.name} · Verlauf`;
  $('#history-list').innerHTML = '';
  $('#history-empty').hidden = true;
  if (!historyDialog.open) historyDialog.showModal();
  try {
    const result = await api(`items/${item.id}/movements`);
    renderHistory(result.movements, item);
  } catch (error) {
    $('#history-list').innerHTML = `<p class="form-error">${escapeHtml(error.message)}</p>`;
  }
}

function renderHistory(movements, item) {
  $('#history-empty').hidden = movements.length !== 0;
  $('#history-list').innerHTML = movements.map((movement) => {
    const signed = `${movement.delta_quantity > 0 ? '+' : ''}${movement.delta_quantity}`;
    const when = new Date(movement.created_at).toLocaleString('de-DE');
    const label = {
      receive: 'Eingelagert', consume: 'Verbraucht', initialize: 'Startbestand', undo: 'Rückgängig',
    }[movement.action] || movement.action;
    const after = movement.quantity_after === null ? 'unbekannt' : movement.quantity_after;
    const undoButton = movement.action !== 'undo' && !movement.undone_by_movement_id
      ? `<button class="button button-quiet history-undo" type="button" data-id="${movement.id}">Rückgängig</button>`
      : `<span class="history-undone">${movement.undone_by_movement_id ? 'Bereits aufgehoben' : ''}</span>`;
    return `<article class="history-row"><div class="history-row-copy"><strong>${escapeHtml(label)} · ${escapeHtml(signed)} Packungen</strong><span>${escapeHtml(when)} · Bestand danach: ${escapeHtml(after)} ${escapeHtml(item.unit || 'Stück')} · ${escapeHtml(movement.source)}</span>${movement.note ? `<small>${escapeHtml(movement.note)}</small>` : ''}</div>${undoButton}</article>`;
  }).join('');
}

async function undoMovement(movementId, itemId) {
  const item = items.find((entry) => entry.id === itemId) || activeDetailItem || activeBookingItem;
  if (!item) return;
  try {
    const result = await api(`movements/${movementId}/undo`, {
      method: 'POST',
      body: JSON.stringify({ idempotency_key: createIdempotencyKey(), source: 'ui' }),
    });
    await loadItems();
    showToast(movementMessage(item, result.movement));
    if (historyDialog.open) await openHistory(activeDetailItem || item);
  } catch (error) {
    showToast(`Rückgängig nicht möglich: ${error.message}`);
  }
}

function closeScanDialog() {
  if (scanDialog.open) scanDialog.close();
  stopCamera();
  setActiveTab(scanReturnView);
}

async function lookupBarcode(rawBarcode) {
  if (barcodeLookupInProgress) return;
  const barcode = String(rawBarcode ?? '').trim();
  if (!barcode) {
    $('#scan-input').focus();
    return;
  }
  if (scannerControls && !scannerBusy) {
    scannerBusy = true;
    pauseCameraAfterDetection();
  }
  barcodeLookupInProgress = true;
  lookupFailed = false;
  const controller = new AbortController();
  lookupAbortController = controller;
  const mode = $('#scan-mode').value;
  const quantity = Math.max(1, Math.floor(Number($('#scan-quantity').value) || 1));
  const result = await lookupBarcodeValue(barcode, async (code, { signal }) => {
    return api(`product-lookup/${encodeURIComponent(code)}`, { signal });
  }, {
    pending: (code) => {
      $('#scan-input').value = code;
      $('#lookup-button').disabled = true;
      $('#lookup-button').textContent = 'Suche …';
      $('#camera-status').textContent = 'Artikel und Produktdaten werden gesucht …';
      $('#camera-status').hidden = false;
      $('#manual-entry-button').hidden = false;
    },
    found: async (item) => {
      const next = bookingForScan(mode, item);
      if (next.action === 'view') {
        closeScanDialog();
        openDetailItem(item);
      } else if (next.action === 'receive' || next.action === 'initialize') {
        closeScanDialog();
        openBookingDialog(item, next.action, 'barcode', quantity);
      } else if (next.action === 'consume') {
        await consumeFromScan(item, quantity);
      } else {
        $('#camera-status').textContent = `${item.name}: Der Bestand ist unbekannt. Es wurde nichts geändert. Wechsle zu „Einlagern“, um einen Startbestand festzulegen.`;
        $('#camera-status').hidden = false;
      }
    },
    identified: async (barcode, product) => {
      if (mode === 'consume') {
        $('#camera-status').textContent = 'Der Code gehört noch nicht zu einem Lagerartikel. Es wurde nichts angelegt oder abgezogen. Wechsle zu „Ansehen“ oder „Einlagern“. ';
        $('#camera-status').hidden = false;
        return;
      }
      pendingCreateBooking = mode === 'receive';
      closeScanDialog();
      openNewItem(barcode, product);
    },
    missing: async (barcode) => {
      if (mode === 'consume') {
        $('#camera-status').textContent = 'Kein gespeicherter Lagerartikel gefunden. Im Verbrauchsmodus wird nichts angelegt oder verändert. Wechsle zu „Ansehen“ oder „Einlagern“. ';
        $('#camera-status').hidden = false;
        return;
      }
      pendingCreateBooking = mode === 'receive';
      closeScanDialog();
      openNewItem(barcode);
    },
    failed: (error, barcode) => {
      lookupFailed = true;
      stopCamera();
      $('#scan-input').value = barcode;
      $('#camera-status').textContent = `Produktsuche nicht verfügbar: ${error.message} Du kannst es erneut versuchen oder den Artikel manuell erfassen.`;
      $('#camera-status').hidden = false;
      $('#manual-entry-button').hidden = mode === 'consume';
    },
    waiting: (_barcode, retryAfterSeconds, attempt) => {
      const seconds = Math.max(1, Math.ceil(retryAfterSeconds));
      $('#camera-status').textContent = `Open Facts begrenzt Anfragen gerade. Automatischer erneuter Versuch in etwa ${seconds} Sekunden (Versuch ${attempt}). Manuelle Erfassung ist jederzeit möglich.`;
      $('#camera-status').hidden = false;
      $('#manual-entry-button').hidden = mode === 'consume';
    },
    cancelled: () => {
      // The manual-entry action or dialog close owns the next UI state.
    },
    settled: () => {
      barcodeLookupInProgress = false;
      if (lookupAbortController === controller) lookupAbortController = undefined;
      $('#lookup-button').disabled = false;
      $('#lookup-button').textContent = lookupFailed ? 'Erneut versuchen' : 'Suchen';
      if (!lookupFailed) $('#manual-entry-button').hidden = true;
    },
  }, { signal: controller.signal, maxRetries: 2, maxWaitMs: 12000 });
  if (result.outcome === 'empty') $('#scan-input').focus();
  if (scanDialog.open) scannerBusy = false;
}

function openManualEntryFromScan() {
  if ($('#scan-mode').value === 'consume') {
    showToast('Im Verbrauchsmodus werden unbekannte Codes nicht angelegt. Wechsle zu „Ansehen“ oder „Einlagern“.');
    return;
  }
  const barcode = $('#scan-input').value.trim();
  lookupAbortController?.abort();
  pendingCreateBooking = $('#scan-mode').value === 'receive';
  closeScanDialog();
  openNewItem(barcode);
}

function pauseCameraAfterDetection() {
  scannerControls?.stop();
  scannerControls = undefined;
  const video = $('#camera-video');
  video.pause();
  video.srcObject = null;
  $('#camera-wrap').hidden = true;
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
      if (duplicateScan(barcode)) return;
      scannerBusy = true;
      pauseCameraAfterDetection();
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

function syncScanMode() {
  const mode = $('#scan-mode').value;
  $('#scan-quantity-field').hidden = mode === 'view';
  $('#camera-status').hidden = true;
  $('#manual-entry-button').hidden = true;
}

function setView(view, { focusSearch = false } = {}) {
  if (!MOBILE_VIEWS.includes(view)) return;
  if (view === 'scanner') {
    scanReturnView = activeView;
    $('#scan-mode').value = 'view';
    $('#scan-quantity').value = '1';
    syncScanMode();
    $('#scan-input').value = '';
    $('#camera-status').hidden = true;
    $('#manual-entry-button').hidden = true;
    $('#lookup-button').disabled = false;
    $('#lookup-button').textContent = 'Suchen';
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
$('#cancel-item').addEventListener('click', () => {
  pendingCreateBooking = false;
  itemDialog.close();
});
$('#close-detail-dialog').addEventListener('click', () => detailDialog.close());
$('#close-detail-button').addEventListener('click', () => detailDialog.close());
$('#detail-edit-button').addEventListener('click', () => {
  if (!activeDetailItem) return;
  detailDialog.close();
  openEditItem(activeDetailItem);
});
$('#detail-book-button').addEventListener('click', () => {
  if (!activeDetailItem) return;
  detailDialog.close();
  openBookingDialog(activeDetailItem, 'receive');
});
$('#detail-history-button').addEventListener('click', () => openHistory(activeDetailItem));
$('#close-scan-dialog').addEventListener('click', closeScanDialog);
$('#camera-button').addEventListener('click', startCamera);
$('#lookup-button').addEventListener('click', () => lookupBarcode($('#scan-input').value));
$('#manual-entry-button').addEventListener('click', openManualEntryFromScan);
$('#scan-mode').addEventListener('change', syncScanMode);
$('#scan-input').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    lookupBarcode($('#scan-input').value);
  }
});
$('#search-input').addEventListener('input', renderFilters);
$('#item-tracking-mode').addEventListener('change', syncTrackingFields);
$('#close-booking-dialog').addEventListener('click', () => bookingDialog.close());
$('#cancel-booking').addEventListener('click', () => bookingDialog.close());
$('#close-history-dialog').addEventListener('click', () => historyDialog.close());
$('#history-close-button').addEventListener('click', () => historyDialog.close());
$('#history-list').addEventListener('click', (event) => {
  const button = event.target.closest('[data-id].history-undo');
  if (button) void undoMovement(Number(button.dataset.id), activeDetailItem?.id);
});
$('#toast').addEventListener('click', (event) => {
  const button = event.target.closest('[data-undo-movement]');
  if (!button) return;
  void undoMovement(Number(button.dataset.undoMovement), Number(button.dataset.itemId));
});
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
  if (itemSaveInProgress) return;
  itemSaveInProgress = true;
  const submitButton = form.querySelector('[type="submit"]');
  submitButton.disabled = true;
  const id = $('#item-id').value;
  const needsInitialBooking = pendingCreateBooking && !id;
  const payload = {
    name: $('#item-name').value,
    barcode: $('#item-barcode').value,
    brand: $('#item-brand').value,
    product_size: $('#item-product-size').value,
    image_url: $('#item-image-url').value,
    image_license: $('#item-image-license').value,
    data_source: $('#item-data-source').value,
    source_url: $('#item-source-url').value,
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
  if (needsInitialBooking) {
    payload.tracking_mode = 'simple';
    payload.stock_status = 'unknown';
    payload.quantity = null;
  }
  try {
    const saved = await api(id ? `items/${id}` : 'items', {
      method: id ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });
    itemDialog.close();
    showToast(id ? 'Artikel aktualisiert.' : 'Artikel hinzugefügt.');
    await loadItems();
    if (needsInitialBooking) {
      pendingCreateBooking = false;
      openBookingDialog(
        saved.item,
        'initialize',
        'barcode',
        Math.max(1, Math.floor(Number($('#scan-quantity').value) || 1)),
      );
    }
  } catch (error) {
    $('#form-error').textContent = error.message;
    $('#form-error').hidden = false;
    if (error.field) document.querySelector(`[name="${error.field}"]`)?.focus();
  } finally {
    itemSaveInProgress = false;
    submitButton.disabled = false;
  }
});

bookingForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (bookingInProgress || !activeBookingItem) return;
  const quantity = Number($('#booking-quantity').value);
  if (!Number.isInteger(quantity) || quantity <= 0) {
    $('#booking-error').textContent = 'Gib eine ganze Anzahl größer 0 ein.';
    $('#booking-error').hidden = false;
    return;
  }
  if (activeBookingAction === 'initialize' && !$('#confirm-initial-stock').checked) {
    $('#booking-error').textContent = 'Bitte bestätige ausdrücklich den Startbestand.';
    $('#booking-error').hidden = false;
    return;
  }
  bookingInProgress = true;
  $('#booking-submit').disabled = true;
  $('#booking-error').hidden = true;
  try {
    const movement = await writeMovement(activeBookingItem, activeBookingAction, quantity, activeBookingSource, {
      initialMode: $('#initial-tracking-mode').value,
    });
    const bookedItem = activeBookingItem;
    bookingDialog.close();
    await loadItems();
    const current = items.find((item) => item.id === bookedItem.id) || bookedItem;
    showUndoToast(current, movement, movementMessage(bookedItem, movement));
  } catch (error) {
    $('#booking-error').textContent = error.message;
    $('#booking-error').hidden = false;
  } finally {
    bookingInProgress = false;
    $('#booking-submit').disabled = false;
  }
});

itemDialog.addEventListener('close', () => {
  if (pendingCreateBooking) pendingCreateBooking = false;
});

scanDialog.addEventListener('close', () => {
  lookupAbortController?.abort();
  stopCamera();
});
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

loadItems();
