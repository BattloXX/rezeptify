function el(id) { return document.getElementById(id); }

function formatDate(value) {
  if (!value) return '–';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('de-AT');
}

function addText(parent, tag, text, className = '') {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  parent.appendChild(node);
}

function renderErrors(errors) {
  const list = el('error-log-list');
  if (!list) return;
  list.replaceChildren();
  if (!errors.length) {
    addText(list, 'p', 'Noch keine Fehler-Einträge vorhanden.');
    return;
  }
  errors.forEach(error => {
    const entry = document.createElement('article');
    entry.className = 'update-log-entry';
    addText(entry, 'h3', `${error.methode || '–'} ${error.pfad || '–'}`);
    addText(entry, 'p', `Zeitpunkt: ${formatDate(error.erstellt_am)}`);
    addText(entry, 'p', `Typ: ${error.exception_typ || 'unbekannt'}`);
    if (error.nachricht) addText(entry, 'pre', error.nachricht, 'error');
    list.appendChild(entry);
  });
}

export async function loadErrorLog() {
  const status = el('error-log-status');
  if (status) status.textContent = 'Fehlerprotokoll wird geladen …';
  try {
    const response = await fetch('/api/system/error-log');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    renderErrors(Array.isArray(data.errors) ? data.errors : []);
    if (status) status.textContent = '';
  } catch (error) {
    if (status) status.textContent = `Fehlerprotokoll konnte nicht geladen werden (${error.message}).`;
  }
}

export function initErrorLog() {}
