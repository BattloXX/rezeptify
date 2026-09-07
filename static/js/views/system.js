import { api } from '../api.js';
import { toast } from '../utils.js';

let updateId = null;
let statusTimer = null;
let healthTimer = null;
let healthStarted = 0;

const progressSteps = [
  ['Backup', 'Backup abgeschlossen'], ['Repository', 'Repository abgeschlossen'],
  ['Abhängigkeiten', 'Abhängigkeiten abgeschlossen'], ['Datenbank', 'Datenbank abgeschlossen'],
];

function el(id) { return document.getElementById(id); }
function result(message, error = false) {
  const node = el('system-result');
  if (node) { node.textContent = message; node.classList.toggle('error', error); }
}

export async function loadSystem() {
  try {
    const health = await fetch('/api/health').then(r => r.json());
    el('system-version').textContent = health.version || '–';
    el('system-db').textContent = health.database === 'ok' ? 'Datenbank erreichbar' : 'Datenbankfehler';
    el('system-db').classList.toggle('error', health.database !== 'ok');
  } catch { result('Systemstatus konnte nicht geladen werden.', true); }
}

export async function checkForUpdate() {
  result('Suche nach Updates …');
  try {
    const data = await api('/api/system/update-check');
    if (!data.update_verfuegbar) return result(data.hinweis || 'Diese Version ist aktuell.');
    result(`Version ${data.neueste_version} ist verfügbar.`);
    el('ov-system-update').classList.add('on');
    el('system-update-pwd').focus();
  } catch (err) { result(err.message, true); }
}

function renderProgress(data) {
  const log = data.log || '';
  const lines = progressSteps.map(([label, done]) => `<li class="${log.includes(done) ? 'done' : ''}">${label} ${log.includes(done) ? '✓' : '…'}</li>`);
  if (data.status === 'neustart_ausgeloest') lines.push('<li>Neustart wird durchgeführt …</li>');
  if (data.status === 'fehlgeschlagen') lines.push('<li class="error">Update fehlgeschlagen.</li>');
  el('system-progress').innerHTML = lines.join('');
}

async function pollStatus() {
  try {
    const data = await api(`/api/system/update-status/${updateId}`);
    renderProgress(data);
    if (data.status === 'fehlgeschlagen') { clearInterval(statusTimer); result(data.fehler || 'Update fehlgeschlagen.', true); return; }
    if (data.status === 'neustart_ausgeloest') { clearInterval(statusTimer); result('Neustart erkannt. Warte auf die neue Version …'); startHealthPolling(); }
  } catch (err) { result(err.message, true); clearInterval(statusTimer); }
}

function startHealthPolling() {
  healthStarted = Date.now();
  healthTimer = setInterval(async () => {
    if (Date.now() - healthStarted > 60000) {
      clearInterval(healthTimer); result('Der Neustart wurde nicht innerhalb von 60 Sekunden bestätigt. Bitte prüfe den Server.', true); return;
    }
    try {
      const health = await fetch('/api/health').then(r => r.ok ? r.json() : Promise.reject());
      clearInterval(healthTimer);
      el('system-version').textContent = health.version || '–';
      result(`Update erfolgreich. Version ${health.version} ist jetzt installiert.`);
    } catch { /* The process is expected to be briefly unavailable. */ }
  }, 2000);
}

export async function confirmSystemUpdate() {
  const password = el('system-update-pwd').value;
  if (!password) return result('Bitte das Passwort eingeben.', true);
  try {
    const data = await api('/api/system/update', { method: 'POST', body: JSON.stringify({ passwort: password }) });
    el('ov-system-update').classList.remove('on');
    el('system-update-pwd').value = '';
    updateId = data.update_id;
    result('Update gestartet.');
    renderProgress({ log: '', status: 'laufend' });
    clearInterval(statusTimer);
    statusTimer = setInterval(pollStatus, 2000);
    pollStatus();
  } catch (err) { result(err.message, true); }
}

export function initSystem() {
  window.checkForUpdate = checkForUpdate;
  window.confirmSystemUpdate = confirmSystemUpdate;
}
