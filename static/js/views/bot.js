import { api } from '../api.js';
import { toast, x } from '../utils.js';
import { openNewForm } from './form.js';

const BOT = { current: null, history: [], running: false };

export function initBot() {
  window.botSearch    = botSearch;
  window.botSetPrompt = botSetPrompt;
  window.botSaveResult  = botSaveResult;
  window.botEditResult  = botEditResult;

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

export function botSetPrompt(text) {
  const inp = document.getElementById('bot-inp');
  if (inp) {
    inp.value = text;
    inp.style.height = 'auto';
    inp.style.height = inp.scrollHeight + 'px';
    inp.focus();
  }
}

async function botSearch() {
  const inp = document.getElementById('bot-inp');
  const q   = inp?.value.trim();
  if (!q || BOT.running) return;
  BOT.running = true;

  setBotStatus(true);
  document.getElementById('bot-results')?.classList.remove('on');

  try {
    const data = await api('/api/rezept-suche', {
      method: 'POST',
      body: JSON.stringify({ query: q })
    });
    BOT.current = { q, data };
    BOT.history.unshift({ q, data });
    if (BOT.history.length > 10) BOT.history.pop();
    renderBotResults(data, q);
    renderBotHistory();
  } catch(e) {
    toast('Suche fehlgeschlagen: ' + e.message, 'err');
  } finally {
    setBotStatus(false);
    BOT.running = false;
  }
}

function renderBotResults(data, q) {
  const container = document.getElementById('bot-results');
  const grid      = document.getElementById('bot-results-grid');
  const hdrEl     = document.getElementById('bot-results-hdr');
  if (!container || !grid) return;

  if (!data?.rezepte?.length) {
    grid.innerHTML = '<p style="color:var(--muted);padding:2rem;text-align:center">Keine Rezepte gefunden. Versuche eine andere Suchanfrage.</p>';
    container.classList.add('on');
    return;
  }

  if (hdrEl) hdrEl.textContent = data.rezepte.length + ' Rezepte für „' + q + '"';

  grid.innerHTML = data.rezepte.map((r, i) => {
    const gz    = (r.zeit_vorb||0)+(r.zeit_koch||0);
    const chips = [
      r.kategorie,
      gz ? gz+' Min.' : null,
      r.portionen ? r.portionen+' Port.' : null,
      r.schwierigkeit
    ].filter(Boolean);
    const ings  = (r.zutaten||[]).filter(z => !z.gruppe).slice(0, 4);
    const src   = data.quellen?.[i];
    return `<div class="bot-card">
      <div class="bot-card-rank"># ${i+1}</div>
      <div class="bot-card-body">
        ${r.kategorie ? `<div class="bot-card-kat">${x(r.kategorie)}</div>` : ''}
        <div class="bot-card-title">${x(r.titel)}</div>
        ${chips.length ? `<div class="bot-card-chips">${chips.map(c=>`<span class="bot-card-chip">${x(c)}</span>`).join('')}</div>` : ''}
        ${r.beschreibung ? `<p class="bot-card-desc">${x(r.beschreibung)}</p>` : ''}
        ${src ? `<div class="bot-suchinfo"><span class="material-symbols-outlined">link</span>${x(src)}</div>` : ''}
        ${ings.length ? `<div class="bot-ing-preview">${ings.map(z=>`<div class="bot-ing-row"><span class="bot-ing-amt">${x(z.menge||'')} ${x(z.einheit||'')}</span><span>${x(z.name)}</span></div>`).join('')}</div>` : ''}
      </div>
      <div class="bot-card-footer">
        <button class="btn btn-accent" onclick="botSaveResult(${i})">
          <span class="material-symbols-outlined">bookmark_add</span> Speichern
        </button>
        <button class="btn btn-ghost" onclick="botEditResult(${i})">
          <span class="material-symbols-outlined">edit</span> Bearbeiten
        </button>
      </div>
    </div>`;
  }).join('');

  container.classList.add('on');
}

function renderBotHistory() {
  const wrap = document.getElementById('bot-history');
  if (!wrap || !BOT.history.length) return;
  wrap.innerHTML = `<div class="bot-history-title">Letzte Suchen</div>` +
    BOT.history.map((h, i) =>
      `<div class="bot-history-item" onclick="botRestoreHistory(${i})">
        <span class="material-symbols-outlined">history</span>
        <span>${x(h.q)}</span>
        <span style="margin-left:auto;font-size:0.72rem;color:var(--muted)">${(h.data?.rezepte?.length||0)} Rezepte</span>
      </div>`
    ).join('');
  window.botRestoreHistory = (i) => {
    const h = BOT.history[i];
    if (!h) return;
    BOT.current = h;
    renderBotResults(h.data, h.q);
    const inp = document.getElementById('bot-inp');
    if (inp) inp.value = h.q;
  };
}

async function botSaveResult(idx) {
  const r = BOT.current?.data?.rezepte?.[idx];
  if (!r) return;
  try {
    const saved = await api('/api/rezepte', {
      method: 'POST',
      body: JSON.stringify({ ...r, quelle_typ: 'bot' })
    });
    if (r.downloaded_image) {
      await api('/api/rezepte/'+saved.id+'/bilder/attach', {
        method: 'POST',
        body: JSON.stringify({ dateiname: r.downloaded_image, ist_haupt: true })
      }).catch(()=>{});
    }
    toast('Rezept gespeichert ✓', 'ok');
  } catch(e) { toast('Fehler: ' + e.message, 'err'); }
}

function botEditResult(idx) {
  const r = BOT.current?.data?.rezepte?.[idx];
  if (!r) return;
  openNewForm({ ...r, quelle_typ: 'bot' });
}

function setBotStatus(on) {
  document.getElementById('bot-status')?.classList.toggle('on', on);
  const btn = document.querySelector('#view-bot .btn-accent');
  if (btn) btn.disabled = on;
}
