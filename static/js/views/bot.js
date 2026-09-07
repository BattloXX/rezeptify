import { api } from '../api.js';
import { toast, x } from '../utils.js';
import { openNewForm } from './form.js';

const BOT = { current: null, history: [], running: false, fallbackQuery: '' };

export function initBot() {
  window.botSearch = botSearch;
  window.botSetPrompt = botSetPrompt;
  window.botSaveResult = botSaveResult;
  window.botEditResult = botEditResult;
  window.botWebFallback = botWebFallback;
  window.openVorschlag = openVorschlag;
  loadBotCategories();
  const inp = document.getElementById('bot-inp');
  if (inp) {
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); botSearch(); }
    });
    inp.addEventListener('input', () => {
      inp.style.height = 'auto';
      inp.style.height = inp.scrollHeight + 'px';
    });
  }
}

async function loadBotCategories() {
  const select = document.getElementById('bot-f-kat');
  if (!select) return;
  const categories = await api('/api/kategorien').catch(() => []);
  select.innerHTML = '<option value="">Alle Kategorien</option>' +
    categories.map(category => `<option value="${x(category)}">${x(category)}</option>`).join('');
}

export function botSetPrompt(text) {
  const inp = document.getElementById('bot-inp');
  if (inp) {
    inp.value = text;
    inp.style.height = 'auto';
    inp.style.height = inp.scrollHeight + 'px';
    inp.focus();
  }
}

function getFilters() {
  const value = id => document.getElementById(id)?.value || '';
  return {
    text: value('bot-inp').trim(),
    max_zeit: value('bot-f-zeit'),
    kategorie: value('bot-f-kat'),
    bewertung_min: value('bot-f-bewertung'),
    schwierigkeit: value('bot-f-diff'),
    vegetarisch: document.getElementById('bot-f-vegetarisch')?.checked,
    vegan: document.getElementById('bot-f-vegan')?.checked,
  };
}

async function botSearch() {
  if (BOT.running) return;
  BOT.running = true;
  BOT.fallbackQuery = getFilters().text;
  setBotStatus(true);
  document.getElementById('bot-results')?.classList.remove('on');
  try {
    const params = new URLSearchParams();
    Object.entries(getFilters()).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    const data = await api('/api/rezepte/vorschlag?' + params);
    renderLocalResults(data, BOT.fallbackQuery);
  } catch (e) {
    toast('Suche fehlgeschlagen: ' + e.message, 'err');
  } finally {
    setBotStatus(false);
    BOT.running = false;
  }
}

function renderLocalResults(data, q) {
  const container = document.getElementById('bot-results');
  const grid = document.getElementById('bot-results-grid');
  const hdrEl = document.getElementById('bot-results-hdr');
  if (!container || !grid) return;
  if (!data?.rezepte?.length) {
    if (hdrEl) hdrEl.textContent = 'Eigene Rezepte';
    grid.innerHTML = '<div class="empty"><div class="empty-icon">🍲</div><h3>Kein passendes eigenes Rezept gefunden.</h3><p>Suche bei Bedarf nach neuen Ideen im Internet.</p><button class="btn btn-accent" onclick="botWebFallback()"><span class="material-symbols-outlined">public</span> Im Internet suchen</button></div>';
    container.classList.add('on');
    return;
  }
  if (hdrEl) hdrEl.textContent = data.rezepte.length + (data.rezepte.length === 1 ? ' eigenes Rezept' : ' eigene Rezepte') + (q ? ` für „${q}“` : '');
  grid.innerHTML = data.rezepte.map((recipe, index) => recipeCard(recipe, index, true)).join('');
  container.classList.add('on');
}

async function botWebFallback() {
  const q = BOT.fallbackQuery;
  if (!q) {
    toast('Bitte beschreibe zuerst, wonach du im Internet suchen möchtest.', 'err');
    return;
  }
  if (BOT.running) return;
  BOT.running = true;
  setBotStatus(true);
  try {
    const data = await api('/api/rezept-suche', { method: 'POST', body: JSON.stringify({ query: q }) });
    BOT.current = { q, data };
    BOT.history.unshift({ q, data });
    if (BOT.history.length > 10) BOT.history.pop();
    renderBotResults(data, q);
    renderBotHistory();
  } catch (e) {
    toast('Internetsuche fehlgeschlagen: ' + e.message, 'err');
  } finally {
    setBotStatus(false);
    BOT.running = false;
  }
}

function recipeCard(r, i, local) {
  const totalTime = (r.zeit_vorb || 0) + (r.zeit_koch || 0);
  const chips = [r.kategorie, totalTime ? totalTime + ' Min.' : null, r.portionen ? r.portionen + ' Port.' : null, r.schwierigkeit].filter(Boolean);
  const ingredients = (r.zutaten || []).filter(z => !z.gruppe).slice(0, 4);
  return `<div class="bot-card">
    <div class="bot-card-rank">${local ? 'Aus deiner Sammlung' : '# ' + (i + 1)}</div>
    <div class="bot-card-body">
      ${r.kategorie ? `<div class="bot-card-kat">${x(r.kategorie)}</div>` : ''}
      <div class="bot-card-title">${x(r.titel)}</div>
      ${chips.length ? `<div class="bot-card-chips">${chips.map(chip => `<span class="bot-card-chip">${x(chip)}</span>`).join('')}</div>` : ''}
      ${r.beschreibung ? `<p class="bot-card-desc">${x(r.beschreibung)}</p>` : ''}
      ${!local && r.suchinfo ? `<div class="bot-suchinfo"><span class="material-symbols-outlined">link</span>${x(r.suchinfo)}</div>` : ''}
      ${ingredients.length ? `<div class="bot-ing-preview">${ingredients.map(z => `<div class="bot-ing-row"><span class="bot-ing-amt">${x(z.menge || '')} ${x(z.einheit || '')}</span><span>${x(z.name)}</span></div>`).join('')}</div>` : ''}
    </div>
    <div class="bot-card-footer">${local
      ? `<button class="btn btn-accent" onclick="openDetail(${r.id})"><span class="material-symbols-outlined">menu_book</span> Rezept öffnen</button>`
      : `<button class="btn btn-accent" onclick="botSaveResult(${i})"><span class="material-symbols-outlined">bookmark_add</span> Speichern</button><button class="btn btn-ghost" onclick="botEditResult(${i})"><span class="material-symbols-outlined">edit</span> Bearbeiten</button>`
    }</div>
  </div>`;
}

function renderBotResults(data, q) {
  const container = document.getElementById('bot-results');
  const grid = document.getElementById('bot-results-grid');
  const hdrEl = document.getElementById('bot-results-hdr');
  if (!container || !grid) return;
  if (!data?.rezepte?.length) {
    grid.innerHTML = '<p style="color:var(--muted);padding:2rem;text-align:center">Keine Rezepte gefunden. Versuche eine andere Suchanfrage.</p>';
  } else {
    if (hdrEl) hdrEl.textContent = data.rezepte.length + ' Internet-Rezepte für „' + q + '“';
    grid.innerHTML = data.rezepte.map((recipe, index) => recipeCard(recipe, index, false)).join('');
  }
  container.classList.add('on');
}

function renderBotHistory() {
  const wrap = document.getElementById('bot-history');
  if (!wrap || !BOT.history.length) return;
  wrap.innerHTML = '<div class="bot-history-title">Letzte Internetsuchen</div>' + BOT.history.map((h, i) =>
    `<div class="bot-history-item" onclick="botRestoreHistory(${i})"><span class="material-symbols-outlined">history</span><span>${x(h.q)}</span><span style="margin-left:auto;font-size:0.72rem;color:var(--muted)">${h.data?.rezepte?.length || 0} Rezepte</span></div>`
  ).join('');
  window.botRestoreHistory = i => {
    const h = BOT.history[i];
    if (!h) return;
    BOT.current = h;
    renderBotResults(h.data, h.q);
    botSetPrompt(h.q);
  };
}

export function openVorschlag(filters = {}) {
  const setValue = (id, value) => { const el = document.getElementById(id); if (el && value !== undefined) el.value = value; };
  setValue('bot-inp', filters.text);
  setValue('bot-f-zeit', filters.max_zeit);
  setValue('bot-f-kat', filters.kategorie);
  setValue('bot-f-bewertung', filters.bewertung_min);
  setValue('bot-f-diff', filters.schwierigkeit);
  if (filters.vegetarisch !== undefined) document.getElementById('bot-f-vegetarisch').checked = !!filters.vegetarisch;
  if (filters.vegan !== undefined) document.getElementById('bot-f-vegan').checked = !!filters.vegan;
  botSearch();
}

async function botSaveResult(idx) {
  const r = BOT.current?.data?.rezepte?.[idx];
  if (!r) return;
  try {
    const saved = await api('/api/rezepte', { method: 'POST', body: JSON.stringify({ ...r, quelle_typ: 'bot' }) });
    if (r.downloaded_image) await api('/api/rezepte/' + saved.id + '/bilder/attach', { method: 'POST', body: JSON.stringify({ dateiname: r.downloaded_image, ist_haupt: true }) }).catch(() => {});
    toast('Rezept gespeichert ✓', 'ok');
  } catch (e) { toast('Fehler: ' + e.message, 'err'); }
}

function botEditResult(idx) {
  const r = BOT.current?.data?.rezepte?.[idx];
  if (r) openNewForm({ ...r, quelle_typ: 'bot' });
}

function setBotStatus(on) {
  document.getElementById('bot-status')?.classList.toggle('on', on);
  const btn = document.querySelector('#view-bot .btn-accent.btn-full');
  if (btn) btn.disabled = on;
}
