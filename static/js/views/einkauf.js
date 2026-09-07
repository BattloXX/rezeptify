import { api } from '../api.js';
import { toast, x, shareText } from '../utils.js';
import { openDetail } from './detail.js';

let entries = [];

export function initEinkauf() {
  document.getElementById('einkauf-add')?.addEventListener('submit', addEntry);
}

export async function loadEinkauf() {
  try {
    entries = (await api('/api/einkaufsliste')).eintraege;
    render();
  } catch (e) { toast(e.message, 'err'); }
}

function amount(entry) {
  return [entry.menge_text || entry.menge, entry.einheit, entry.name].filter(v => v !== null && v !== undefined && v !== '').join(' ');
}

function originTags(entry) {
  return (entry.herkunft || []).map(o => o.rezept_id
    ? `<button class="shopping-origin" data-recipe="${o.rezept_id}">${x(o.rezept_titel || 'Rezept')}</button>`
    : `<span class="shopping-origin">${x(o.rezept_titel || '')}</span>`).join('');
}

function rows(list) {
  if (!list.length) return '<p class="shopping-empty">Keine Einträge</p>';
  return list.map(e => `<div class="shopping-row ${e.erledigt ? 'done' : ''}" data-id="${e.id}">
    <button class="shopping-check" aria-label="Erledigt" data-toggle="${e.id}"><span class="material-symbols-outlined">${e.erledigt ? 'check_box' : 'check_box_outline_blank'}</span></button>
    <div class="shopping-main"><strong>${x(amount(e))}</strong><div class="shopping-origins">${originTags(e)}</div></div>
    <button class="shopping-delete" aria-label="Löschen" data-delete="${e.id}"><span class="material-symbols-outlined">delete</span></button>
  </div>`).join('');
}

function render() {
  const open = entries.filter(e => !e.erledigt), done = entries.filter(e => e.erledigt);
  document.getElementById('einkauf-open').innerHTML = rows(open);
  document.getElementById('einkauf-done').innerHTML = rows(done);
  document.getElementById('einkauf-clean').hidden = !done.length;
  document.querySelectorAll('[data-toggle]').forEach(b => b.onclick = () => toggle(Number(b.dataset.toggle)));
  document.querySelectorAll('[data-delete]').forEach(b => b.onclick = () => remove(Number(b.dataset.delete)));
  document.querySelectorAll('[data-recipe]').forEach(b => b.onclick = () => openDetail(Number(b.dataset.recipe)));
}

async function toggle(id) {
  const entry = entries.find(e => e.id === id); if (!entry) return;
  const old = entry.erledigt; entry.erledigt = !old; render();
  try { await api('/api/einkaufsliste/' + id, { method: 'PATCH', body: JSON.stringify({ erledigt: entry.erledigt }) }); }
  catch (e) { entry.erledigt = old; render(); toast(e.message, 'err'); }
}

async function remove(id) {
  try { await api('/api/einkaufsliste/' + id, { method: 'DELETE' }); entries = entries.filter(e => e.id !== id); render(); }
  catch (e) { toast(e.message, 'err'); }
}

async function addEntry(event) {
  event.preventDefault();
  const input = document.getElementById('einkauf-name'), name = input.value.trim();
  if (!name) return;
  try { entries.unshift(await api('/api/einkaufsliste', { method: 'POST', body: JSON.stringify({ name }) })); input.value = ''; render(); }
  catch (e) { toast(e.message, 'err'); }
}

export async function clearDone() {
  try { await api('/api/einkaufsliste/aufraeumen', { method: 'POST', body: '{}' }); entries = entries.filter(e => !e.erledigt); render(); }
  catch (e) { toast(e.message, 'err'); }
}

export async function shareShopping() {
  const body = entries.filter(e => !e.erledigt).map(e => `• ${amount(e)}`).join('\n') || 'Keine offenen Einträge';
  await shareText('Einkaufsliste', body);
}

window.clearDone = clearDone;
window.shareShopping = shareShopping;
