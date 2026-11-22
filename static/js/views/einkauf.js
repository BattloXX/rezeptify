import store from '../einkauf-store.js';
import { formatAmount, unitMultiplier } from '../einkauf-core.js';
import { parseEintrag, splitMehrfach } from '../mengen-parser.js';
import { toast, toastAction, x, shareText } from '../utils.js';
import { openDetail } from './detail.js';

let entries = [];
let armedRecipe = null, recipeTimer, editing, previousFocus;
let suppressClick = false;

export function initEinkauf() {
  document.getElementById('einkauf-add')?.addEventListener('submit', addEntry);
  const input = document.getElementById('einkauf-name');
  input?.addEventListener('input', preview);
  input?.addEventListener('paste', event => {
    const text = event.clipboardData?.getData('text');
    if (!text || !/[\r\n]/u.test(text)) return;
    event.preventDefault();
    addText(text, true);
  });
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (Recognition) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'btn btn-ghost shopping-mic';
    button.setAttribute('aria-label', 'Spracheingabe');
    button.innerHTML = '<span class="material-symbols-outlined">mic</span>';
    input.after(button);
    button.addEventListener('click', () => {
      const recognition = new Recognition();
      recognition.lang = 'de-AT';
      recognition.onresult = event => {
        input.value = event.results[0][0].transcript.replace(/ und /giu, ', ');
        preview(); input.focus();
      };
      recognition.onerror = () => toast('Spracheingabe nicht verfügbar', 'err');
      recognition.start();
    });
  }
  const overlay = document.getElementById('ov-einkauf-edit');
  overlay?.addEventListener('click', event => {
    if (event.target === overlay || event.target.closest('[data-edit-cancel]')) closeEdit();
    const chip = event.target.closest('[data-unit]');
    if (chip) { document.getElementById('einkauf-edit-unit').value = chip.dataset.unit; updateUnitChips(); }
    if (event.target.closest('[data-edit-delete]') && editing) { const id = editing.uuid; closeEdit(); remove(id); }
  });
  overlay?.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.stopPropagation(); closeEdit(); }
    if (event.key === 'Tab') {
      const controls = [...overlay.querySelectorAll('button,input')].filter(el => !el.disabled);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  document.getElementById('einkauf-edit')?.addEventListener('submit', saveEdit);
  document.getElementById('einkauf-edit-unit')?.addEventListener('input', updateUnitChips);
  for (const id of ['einkauf-open', 'einkauf-done']) document.getElementById(id)?.addEventListener('click', event => {
    if (suppressClick) { event.preventDefault(); return; }
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.toggle) toggle(button.dataset.toggle);
    if (button.dataset.delete) remove(button.dataset.delete);
    if (button.dataset.recipe) openDetail(Number(button.dataset.recipe));
    if (button.dataset.removeRecipe) confirmRecipe(Number(button.dataset.removeRecipe));
    if (button.dataset.edit) openEdit(button.dataset.edit);
    if (button.dataset.plus) {
      try { store.plus(button.dataset.plus, Number(button.dataset.delta)); }
      catch (e) { toast(e.message, 'err'); }
    }
  });
  for (const id of ['einkauf-open', 'einkauf-done']) initSwipe(document.getElementById(id));
  store.addEventListener('change', render);
  store.addEventListener('status', renderStatus);
}

export async function loadEinkauf() {
  await store.init();
  render();
  store.scheduleSync(0);
}

function amount(entry) { return formatAmount(entry); }

function step(entry) {
  return { g:100, kg:0.5, ml:250, l:0.5 }[entry.einheit?.toLowerCase()] || 1;
}

function originTags(entry) {
  const seen = new Set();
  return (entry.herkunft || []).filter(o => {
    if (!o.rezept_id) return true;
    if (seen.has(o.rezept_id)) return false;
    seen.add(o.rezept_id); return true;
  }).map(o => o.rezept_id
    ? `<span class="shopping-origin ${armedRecipe === Number(o.rezept_id) ? 'armed' : ''}"><button data-recipe="${Number(o.rezept_id)}">${x(o.rezept_titel || 'Rezept')}</button><button data-remove-recipe="${Number(o.rezept_id)}" aria-label="Rezeptanteil entfernen">${armedRecipe === Number(o.rezept_id) ? 'Entfernen?' : '×'}</button></span>`
    : `<span class="shopping-origin">${x(o.rezept_titel || '')}</span>`).join('');
}

function rows(list) {
  if (!list.length) return '<p class="shopping-empty">Keine Einträge</p>';
  return list.map(e => `<div class="shopping-swipe"><span class="shopping-swipe-icon material-symbols-outlined" aria-hidden="true"></span><div class="shopping-row ${e.erledigt ? 'done' : ''}" data-id="${x(e.uuid)}">
    <button class="shopping-check" aria-label="${e.erledigt ? 'Wieder öffnen' : 'Abhaken'}" data-toggle="${x(e.uuid)}"><span class="material-symbols-outlined">${e.erledigt ? 'check_box' : 'check_box_outline_blank'}</span></button>
    <div class="shopping-main"><button class="shopping-text" data-edit="${x(e.uuid)}"><strong>${x(amount(e))}</strong>${e.notiz ? `<small>${x(e.notiz)}</small>` : ''}</button><div class="shopping-origins">${originTags(e)}</div></div>
    ${!e.erledigt && !e.menge_text ? `<div class="shopping-stepper"><button data-plus="${x(e.uuid)}" data-delta="${-step(e)}" aria-label="Menge verringern" ${(e.menge ?? (e.einheit ? 0 : 1)) <= step(e) ? 'disabled' : ''}>−</button><button data-plus="${x(e.uuid)}" data-delta="${step(e)}" aria-label="Menge erhöhen">+</button></div>` : ''}
    <button class="shopping-delete" aria-label="Löschen" data-delete="${x(e.uuid)}"><span class="material-symbols-outlined">delete</span></button>
  </div></div>`).join('');
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

function preview() {
  const parts = splitMehrfach(document.getElementById('einkauf-name').value);
  const line = document.getElementById('einkauf-preview');
  line.hidden = !parts.length;
  if (parts.length > 1) line.textContent = `${parts.length} Einträge: ${parts.join(', ')}`;
  else if (parts.length) {
    const entry = parseEintrag(parts[0]);
    const quantity = formatAmount({ ...entry, name: null });
    line.textContent = [quantity, entry.name, entry.notiz].filter(Boolean).join(' · ');
  }
}

function addText(text, pasted = false) {
  const parsed = splitMehrfach(text).map(parseEintrag);
  if (!parsed.length) return;
  if (parsed.some(e => !e.name || e.name.length > 255 || (e.notiz || '').length > 255 ||
      (e.menge_text || '').length > 64 || (e.menge !== null && Math.abs(e.menge) > 9999999.999))) {
    toast('Ungültiger Eintrag', 'err'); return;
  }
  const undo = [];
  let merged;
  try {
    for (const entry of parsed) {
      const before = new Map(store.entries().map(row => [row.uuid, structuredClone(row)]));
      const id = store.add(entry.name, entry);
      const row = store.entries().find(e => e.uuid === id), old = before.get(id);
      if (old) {
        const delta = (row.menge * unitMultiplier(row.einheit) - (old.menge ?? (old.einheit ? 0 : 1)) * unitMultiplier(old.einheit)) / unitMultiplier(row.einheit);
        const unit = row.einheit;
        undo.push(() => {
          const current = store.entries().find(e => e.uuid === id);
          if (current) store.plus(id, -delta * unitMultiplier(unit) / unitMultiplier(current.einheit));
        });
        merged = row;
      } else undo.push(() => store.remove(id));
    }
    document.getElementById('einkauf-name').value = ''; preview();
    if (pasted || parsed.length > 1 || merged) {
      const message = parsed.length === 1 && merged && !pasted
        ? `${merged.name}: jetzt ${formatAmount({ ...merged, name: null })}`
        : `${parsed.length} Einträge hinzugefügt`;
      toastAction(message, 'Rückgängig', () => undo.reverse().forEach(fn => fn()));
    }
  } catch (e) {
    toast(e.message, 'err');
  }
}

function addEntry(event) {
  event.preventDefault();
  addText(document.getElementById('einkauf-name').value);
}

function confirmRecipe(id) {
  clearTimeout(recipeTimer);
  if (armedRecipe === id) {
    armedRecipe = null;
    try { store.removeRecipe(id); } catch (e) { toast(e.message, 'err'); }
  } else {
    armedRecipe = id;
    recipeTimer = setTimeout(() => { armedRecipe = null; render(); }, 3000);
  }
  render();
}

function openEdit(id) {
  editing = structuredClone(entries.find(e => e.uuid === id));
  if (!editing) return;
  previousFocus = document.activeElement;
  for (const [field, value] of Object.entries({ name:editing.name, amount:editing.menge == null ? null : String(editing.menge).replace('.', ','), unit:editing.einheit, text:editing.menge_text, note:editing.notiz }))
    document.getElementById(`einkauf-edit-${field}`).value = value ?? '';
  updateUnitChips();
  document.getElementById('ov-einkauf-edit').classList.add('on');
  document.getElementById('einkauf-edit-name').focus();
}

function updateUnitChips() {
  const unit = document.getElementById('einkauf-edit-unit').value;
  for (const chip of document.querySelectorAll('#ov-einkauf-edit [data-unit]'))
    chip.setAttribute('aria-pressed', String(chip.dataset.unit === unit));
}

function closeEdit() {
  document.getElementById('ov-einkauf-edit').classList.remove('on');
  editing = null;
  if (previousFocus?.isConnected) previousFocus.focus();
}

function saveEdit(event) {
  event.preventDefault();
  if (!editing) return;
  const get = key => document.getElementById(`einkauf-edit-${key}`).value.trim();
  const name = get('name'), notiz = get('note') || null, menge_text = get('text') || null;
  const raw = get('amount'), menge = menge_text || !raw ? null : Number(raw.replace(',', '.'));
  const einheit = get('unit') || null;
  if (!name || (menge !== null && (!Number.isFinite(menge) || menge < 0 || menge > 9999999.999))) {
    toast('Name und gültige Menge eingeben', 'err'); return;
  }
  try {
    if (name !== editing.name) store.rename(editing.uuid, name);
    if (notiz !== editing.notiz) store.setNote(editing.uuid, notiz);
    if (menge !== editing.menge || einheit !== editing.einheit || menge_text !== editing.menge_text)
      store.setAmount(editing.uuid, menge, einheit, menge_text);
    closeEdit();
  } catch (e) { toast(e.message, 'err'); }
}

function initSwipe(container) {
  if (!container) return;
  let gesture;
  const reset = () => {
    if (gesture) {
      gesture.row.style.transform = '';
      gesture.row.classList.remove('swiping');
      gesture.row.parentElement.classList.remove('swipe-right', 'swipe-left');
    }
    gesture = null;
  };
  container.addEventListener('pointerdown', event => {
    if (!event.isPrimary || (event.pointerType === 'mouse' && event.button !== 0)) return;
    const row = event.target.closest('.shopping-row');
    if (row) gesture = { row, id:event.pointerId, x:event.clientX, y:event.clientY, dx:0, active:false };
  });
  container.addEventListener('pointermove', event => {
    if (!gesture || gesture.id !== event.pointerId) return;
    const dx = event.clientX - gesture.x, dy = event.clientY - gesture.y;
    if (!gesture.active && Math.abs(dy) > 10 && Math.abs(dy) >= Math.abs(dx)) { reset(); return; }
    if (!gesture.active && Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy)) {
      gesture.active = true; gesture.row.setPointerCapture(event.pointerId);
    }
    if (!gesture.active) return;
    gesture.dx = dx;
    gesture.row.classList.add('swiping');
    gesture.row.style.transform = `translateX(${dx}px)`;
    const wrapper = gesture.row.parentElement;
    wrapper.classList.toggle('swipe-right', dx > 0); wrapper.classList.toggle('swipe-left', dx < 0);
    wrapper.querySelector('.shopping-swipe-icon').textContent = dx > 0 ? 'check' : 'delete';
  });
  container.addEventListener('pointerup', event => {
    if (!gesture || gesture.id !== event.pointerId) return;
    const { row, dx, active } = gesture;
    const trigger = active && Math.abs(dx) > row.getBoundingClientRect().width * 0.35;
    if (active) {
      suppressClick = true;
      setTimeout(() => { suppressClick = false; }, 0);
    }
    reset();
    if (trigger) { if (dx > 0) toggle(row.dataset.id); else remove(row.dataset.id); }
  });
  container.addEventListener('pointercancel', reset);
  container.addEventListener('lostpointercapture', reset);
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
