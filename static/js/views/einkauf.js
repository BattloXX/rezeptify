import store from '../einkauf-store.js';
import { toast, toastAction, x, shareText } from '../utils.js';
import { openDetail } from './detail.js';

let entries = [];

export function initEinkauf() {
  document.getElementById('einkauf-add')?.addEventListener('submit', addEntry);
  for (const id of ['einkauf-open', 'einkauf-done']) document.getElementById(id)?.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.toggle) toggle(button.dataset.toggle);
    if (button.dataset.delete) remove(button.dataset.delete);
    if (button.dataset.recipe) openDetail(Number(button.dataset.recipe));
  });
  store.addEventListener('change', render);
  store.addEventListener('status', renderStatus);
}

export async function loadEinkauf() {
  await store.init();
  render();
  store.scheduleSync(0);
}

function amount(entry) {
  return [entry.menge_text || entry.menge, entry.einheit, entry.name].filter(v => v !== null && v !== undefined && v !== '').join(' ');
}

function originTags(entry) {
  return (entry.herkunft || []).map(o => o.rezept_id
    ? `<button class="shopping-origin" data-recipe="${Number(o.rezept_id)}">${x(o.rezept_titel || 'Rezept')}</button>`
    : `<span class="shopping-origin">${x(o.rezept_titel || '')}</span>`).join('');
}

function rows(list) {
  if (!list.length) return '<p class="shopping-empty">Keine Einträge</p>';
  return list.map(e => `<div class="shopping-row ${e.erledigt ? 'done' : ''}" data-id="${x(e.uuid)}">
    <button class="shopping-check" aria-label="Erledigt" data-toggle="${x(e.uuid)}"><span class="material-symbols-outlined">${e.erledigt ? 'check_box' : 'check_box_outline_blank'}</span></button>
    <div class="shopping-main"><strong>${x(amount(e))}</strong><div class="shopping-origins">${originTags(e)}</div></div>
    <button class="shopping-delete" aria-label="Löschen" data-delete="${x(e.uuid)}"><span class="material-symbols-outlined">delete</span></button>
  </div>`).join('');
}

function render() {
  entries = store.entries();
  renderStatus();
  const open = entries.filter(e => !e.erledigt), done = entries.filter(e => e.erledigt);
  document.getElementById('einkauf-open').innerHTML = rows(open);
  document.getElementById('einkauf-done').innerHTML = rows(done);
  document.getElementById('einkauf-clean').hidden = !done.length;
}

function renderStatus() {
  const el = document.getElementById('einkauf-status');
  if (!el) return;
  const status = store.status();
  el.className = 'shopping-status' + (!status.online ? ' offline' : status.fehler ? ' problem' : '');
  el.textContent = !status.online ? `Offline – ${status.pending} Änderungen ausstehend`
    : status.fehler ? 'Verbindungsproblem – neuer Versuch …'
    : status.pending ? `${status.pending} Änderungen ausstehend` : 'Synchron';
}

function toggle(id) {
  const entry = entries.find(e => e.uuid === id); if (!entry) return;
  const old = entry.erledigt;
  try {
    store.toggle(id);
    toastAction(old ? 'Wieder offen' : 'Abgehakt', 'Rückgängig', () => store.setDone(id, old));
  } catch (e) { toast(e.message, 'err'); }
}

function restore(entry) {
  store.restore(entry);
}

function remove(id) {
  const entry = entries.find(e => e.uuid === id); if (!entry) return;
  try {
    store.remove(id);
    toastAction('Eintrag gelöscht', 'Rückgängig', () => restore(entry));
  } catch (e) { toast(e.message, 'err'); }
}

function addEntry(event) {
  event.preventDefault();
  const input = document.getElementById('einkauf-name'), name = input.value.trim();
  if (!name) return;
  try { store.add(name); input.value = ''; }
  catch (e) { toast(e.message, 'err'); }
}

export function clearDone() {
  const done = entries.filter(e => e.erledigt);
  try {
    store.clearDone();
    if (done.length) toastAction('Erledigte gelöscht', 'Rückgängig', () => done.forEach(restore));
  } catch (e) { toast(e.message, 'err'); }
}

export async function shareShopping() {
  const body = entries.filter(e => !e.erledigt).map(e => `• ${amount(e)}`).join('\n') || 'Keine offenen Einträge';
  await shareText('Einkaufsliste', body);
}

window.clearDone = clearDone;
window.shareShopping = shareShopping;
