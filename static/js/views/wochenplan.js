import { api } from '../api.js';
import { toast, x } from '../utils.js';
import { openDetail } from './detail.js';

let entries = [];
let pickerDay = null;

function week() {
  const d = new Date(); d.setHours(0, 0, 0, 0);
  const mondayOffset = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - mondayOffset);
  return Array.from({ length: 7 }, (_, i) => { const day = new Date(d); day.setDate(d.getDate() + i); return day; });
}
function iso(d) { return d.toISOString().slice(0, 10); }

export function initWochenplan() {
  document.getElementById('plan-picker-search')?.addEventListener('input', renderPicker);
}

export async function loadWochenplan() {
  const days = week();
  try {
    entries = (await api(`/api/wochenplan?von=${iso(days[0])}&bis=${iso(days[6])}`)).eintraege;
    render();
  } catch (e) { toast(e.message, 'err'); }
}

function render() {
  const days = week();
  document.getElementById('wochenplan-range').textContent = `${days[0].toLocaleDateString('de-AT', { day: '2-digit', month: '2-digit' })} – ${days[6].toLocaleDateString('de-AT', { day: '2-digit', month: '2-digit', year: 'numeric' })}`;
  document.getElementById('wochenplan-days').innerHTML = days.map(day => {
    const date = iso(day), planned = entries.filter(e => e.datum === date);
    return `<article class="plan-day"><header><strong>${x(day.toLocaleDateString('de-AT', { weekday: 'long' }))}</strong><span>${day.toLocaleDateString('de-AT', { day: '2-digit', month: '2-digit' })}</span></header>
      <div class="plan-items">${planned.length ? planned.map(card).join('') : '<p class="plan-empty">Noch nichts geplant</p>'}</div>
      <button class="btn btn-ghost plan-add" data-add="${date}"><span class="material-symbols-outlined">add</span> Rezept hinzufügen</button>
    </article>`;
  }).join('');
  document.querySelectorAll('[data-add]').forEach(button => button.onclick = () => openPicker(button.dataset.add));
  document.querySelectorAll('[data-open]').forEach(button => button.onclick = () => openDetail(Number(button.dataset.open)));
  document.querySelectorAll('[data-remove]').forEach(button => button.onclick = () => remove(Number(button.dataset.remove)));
}

function card(entry) {
  const image = entry.haupt_bild ? `<img src="${x(entry.haupt_bild)}" alt="">` : '<span class="material-symbols-outlined">restaurant</span>';
  return `<div class="plan-card"><button class="plan-card-main" data-open="${entry.rezept_id}"><span class="plan-thumb">${image}</span><span><small>${x(entry.mahlzeit)}</small>${x(entry.titel)}</span></button><button class="plan-remove" data-remove="${entry.id}" aria-label="Entfernen">×</button></div>`;
}

function openPicker(day) {
  pickerDay = day;
  document.getElementById('plan-picker-search').value = '';
  document.getElementById('plan-picker-day').textContent = new Date(`${day}T00:00:00`).toLocaleDateString('de-AT', { weekday: 'long', day: '2-digit', month: 'long' });
  document.getElementById('ov-plan-picker').classList.add('on');
  renderPicker();
}

async function renderPicker() {
  const q = document.getElementById('plan-picker-search').value.trim();
  try {
    const recipes = (await api('/api/rezepte?limit=200' + (q ? `&suche=${encodeURIComponent(q)}` : ''))).items;
    document.getElementById('plan-picker-list').innerHTML = recipes.length ? recipes.map(r => `<button class="plan-picker-item" data-recipe="${r.id}">${r.haupt_bild ? `<img src="${x(r.haupt_bild)}" alt="">` : '<span class="material-symbols-outlined">restaurant</span>'}<span>${x(r.titel)}</span></button>`).join('') : '<p class="plan-empty">Keine Rezepte gefunden</p>';
    document.querySelectorAll('[data-recipe]').forEach(button => button.onclick = () => addRecipe(Number(button.dataset.recipe)));
  } catch (e) { toast(e.message, 'err'); }
}

async function addRecipe(rezeptId) {
  try {
    await api('/api/wochenplan', { method: 'POST', body: JSON.stringify({ rezept_id: rezeptId, datum: pickerDay, mahlzeit: document.getElementById('plan-picker-meal').value }) });
    document.getElementById('ov-plan-picker').classList.remove('on'); await loadWochenplan();
  } catch (e) { toast(e.message, 'err'); }
}

async function remove(id) {
  try { await api('/api/wochenplan/' + id, { method: 'DELETE' }); entries = entries.filter(e => e.id !== id); render(); }
  catch (e) { toast(e.message, 'err'); }
}

export async function createWeekShopping() {
  const days = week();
  try {
    const result = await api('/api/wochenplan/einkaufsliste', { method: 'POST', body: JSON.stringify({ von: iso(days[0]), bis: iso(days[6]) }) });
    toast(`${result.anzahl} Einträge zur Einkaufsliste hinzugefügt`, 'ok');
    window.showView('einkauf');
  } catch (e) { toast(e.message, 'err'); }
}
window.createWeekShopping = createWeekShopping;
