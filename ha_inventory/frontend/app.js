const API = new URL('api/', document.baseURI).toString();
const $ = (selector) => document.querySelector(selector);
const itemDialog = $('#item-dialog');
const scanDialog = $('#scan-dialog');
const form = $('#item-form');
let items = [];
let activeCategory = '';
let toastTimeout;
let cameraStream;
let scanFrame;
let scannerBusy = false;

async function api(path, options = {}) {
  const response = await fetch(new URL(path, API), {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
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

function formatQuantity(value) {
  return new Intl.NumberFormat('de-DE', { maximumFractionDigits: 2 }).format(value);
}

function iconFor(category) {
  const icons = { Lebensmittel: '◉', Werkzeuge: '⌁', Haushalt: '⌂', Sonstiges: '▦' };
  return icons[category] || '▦';
}

function render() {
  $('#stat-items').textContent = items.length;
  $('#stat-low').textContent = items.filter((item) => item.minimum_quantity > 0 && item.quantity <= item.minimum_quantity).length;
  $('#stat-locations').textContent = new Set(items.map((item) => item.location.trim()).filter(Boolean)).size;
  renderFilters();
}

function renderFilters() {
  const categories = [...new Set(items.map((item) => item.category))].sort((a, b) => a.localeCompare(b, 'de'));
  const available = ['', ...categories];
  if (!available.includes(activeCategory)) activeCategory = '';
  $('#category-filters').innerHTML = [
    `<button class="filter-chip ${activeCategory === '' ? 'active' : ''}" data-category="" type="button">Alle</button>`,
    ...categories.map((category) => `<button class="filter-chip ${activeCategory === category ? 'active' : ''}" data-category="${escapeHtml(category)}" type="button">${escapeHtml(category)}</button>`),
  ].join('');
  const query = $('#search-input').value.trim().toLocaleLowerCase('de');
  const filtered = items.filter((item) => {
    const categoryMatch = !activeCategory || item.category === activeCategory;
    const text = `${item.name} ${item.barcode || ''} ${item.location}`.toLocaleLowerCase('de');
    return categoryMatch && (!query || text.includes(query));
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
}

function renderItem(item) {
  const isLow = item.minimum_quantity > 0 && item.quantity <= item.minimum_quantity;
  return `<article class="item-row">
    <div class="item-main">
      <span class="item-symbol" aria-hidden="true">${iconFor(item.category)}</span>
      <div class="item-copy">
        <div class="item-name">${escapeHtml(item.name)}</div>
        <div class="item-barcode">${item.barcode ? `▤ ${escapeHtml(item.barcode)}` : 'Kein Barcode'}</div>
      </div>
    </div>
    <span class="item-category">${escapeHtml(item.category)}</span>
    <span class="item-quantity ${isLow ? 'low-stock' : ''}">${formatQuantity(item.quantity)} ${escapeHtml(item.unit)}${isLow ? ' · knapp' : ''}</span>
    <span class="item-location">${item.location ? `<span class="location-value">⌖ ${escapeHtml(item.location)}</span>` : '<span class="location-value">–</span>'}</span>
    <div class="row-actions">
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
  $('#item-quantity').value = '1';
  $('#item-unit').value = 'Stück';
  $('#item-minimum').value = '0';
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
  $('#item-quantity').value = item.quantity;
  $('#item-unit').value = item.unit;
  $('#item-minimum').value = item.minimum_quantity;
  $('#item-notes').value = item.notes;
  $('#form-title').textContent = 'Artikel bearbeiten';
  itemDialog.showModal();
  $('#item-name').focus();
}

function closeScanDialog() {
  scanDialog.close();
  stopCamera();
}

async function lookupBarcode(rawBarcode) {
  const barcode = rawBarcode.trim();
  if (!barcode) {
    $('#scan-input').focus();
    return;
  }
  try {
    const { item } = await api(`items/barcode/${encodeURIComponent(barcode)}`);
    closeScanDialog();
    const position = items.findIndex((entry) => entry.id === item.id);
    if (position >= 0) {
      activeCategory = '';
      $('#search-input').value = '';
      render();
      document.querySelector(`[data-id="${item.id}"].edit-item`)?.closest('.item-row')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    showToast(`Schon erfasst: ${item.name} · Bestand bleibt unverändert.`);
  } catch (error) {
    if (error.status === 404) {
      closeScanDialog();
      openNewItem(barcode);
      return;
    }
    showToast(error.message);
  }
}

async function startCamera() {
  const status = $('#camera-status');
  const wrap = $('#camera-wrap');
  if (!('BarcodeDetector' in window)) {
    status.textContent = 'Dieser Browser unterstützt keinen Kamera-Barcode-Scan. Nutze die Eingabe unten.';
    status.hidden = false;
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    status.textContent = 'Die Kamera ist nur auf einer sicheren HTTPS-Seite verfügbar. Du kannst den Barcode unten eingeben.';
    status.hidden = false;
    return;
  }
  try {
    const supported = await window.BarcodeDetector.getSupportedFormats();
    const formats = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128'].filter((format) => supported.includes(format));
    const detector = new window.BarcodeDetector({ formats: formats.length ? formats : supported });
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
    const video = $('#camera-video');
    video.srcObject = cameraStream;
    await video.play();
    wrap.hidden = false;
    status.hidden = true;
    scannerBusy = false;
    const detect = async () => {
      if (!cameraStream || scannerBusy) return;
      try {
        const codes = await detector.detect(video);
        if (codes.length && codes[0].rawValue) {
          scannerBusy = true;
          await lookupBarcode(codes[0].rawValue);
          return;
        }
      } catch (_) {
        // A frame may not be ready yet; continue scanning.
      }
      if (cameraStream) scanFrame = requestAnimationFrame(detect);
    };
    scanFrame = requestAnimationFrame(detect);
  } catch (error) {
    status.textContent = error.name === 'NotAllowedError'
      ? 'Kamerazugriff verweigert. Erlaube den Zugriff im Browser oder gib den Barcode ein.'
      : 'Kamera konnte nicht geöffnet werden. Gib den Barcode unten ein.';
    status.hidden = false;
  }
}

function stopCamera() {
  if (scanFrame) cancelAnimationFrame(scanFrame);
  scanFrame = undefined;
  cameraStream?.getTracks().forEach((track) => track.stop());
  cameraStream = undefined;
  scannerBusy = false;
  $('#camera-video').srcObject = null;
  $('#camera-wrap').hidden = true;
}

$('#add-button').addEventListener('click', () => openNewItem());
$('#empty-add-button').addEventListener('click', () => openNewItem());
$('#scan-button').addEventListener('click', () => {
  $('#scan-input').value = '';
  $('#camera-status').hidden = true;
  scanDialog.showModal();
  $('#scan-input').focus();
});
$('#close-item-dialog').addEventListener('click', () => itemDialog.close());
$('#cancel-item').addEventListener('click', () => itemDialog.close());
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
$('#category-filters').addEventListener('click', (event) => {
  const button = event.target.closest('[data-category]');
  if (!button) return;
  activeCategory = button.dataset.category;
  renderFilters();
});
$('#item-list').addEventListener('click', async (event) => {
  const editButton = event.target.closest('.edit-item');
  const deleteButton = event.target.closest('.delete-item');
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
    quantity: Number($('#item-quantity').value),
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
document.addEventListener('keydown', (event) => {
  if (event.key === '/' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
    event.preventDefault();
    $('#search-input').focus();
  }
  if (event.key === 'Escape' && scanDialog.open) stopCamera();
});

if ('BarcodeDetector' in window && window.isSecureContext && navigator.mediaDevices?.getUserMedia) {
  $('#camera-button').hidden = false;
}

loadItems();
