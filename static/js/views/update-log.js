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

function renderUpdates(updates) {
  const list = el('update-log-list');
  if (!list) return;
  list.replaceChildren();
  if (!updates.length) {
    addText(list, 'p', 'Noch keine Update-Einträge vorhanden.');
    return;
  }
  updates.forEach(update => {
    const entry = document.createElement('article');
    entry.className = 'update-log-entry';
    addText(entry, 'h3', `${update.status || 'unbekannt'} · ${update.von_version || '–'} → ${update.ziel_version || '–'}`);
    addText(entry, 'p', `Gestartet: ${formatDate(update.gestartet_am)}`);
    addText(entry, 'p', `Beendet: ${formatDate(update.beendet_am)}`);
    if (update.fehler) addText(entry, 'p', `Fehler: ${update.fehler}`, 'error');
    if (update.log) addText(entry, 'pre', update.log);
    list.appendChild(entry);
  });
}

export async function loadUpdateLog() {
  const status = el('update-log-status');
  if (status) status.textContent = 'Update-Verlauf wird geladen …';
  try {
    const response = await fetch('/api/system/update-log');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    renderUpdates(Array.isArray(data.updates) ? data.updates : []);
    if (status) status.textContent = '';
  } catch (error) {
    if (status) status.textContent = `Update-Verlauf konnte nicht geladen werden (${error.message}).`;
  }
}

export function initUpdateLog() {}
