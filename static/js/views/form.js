import { api, apiFetch } from '../api.js';
import { toast, x } from '../utils.js';
import { S } from '../app.js';
import { loadGrid, loadTags } from './home.js';
import { closeOverlay } from './detail.js';

// ── Open form ─────────────────────────────────────────────────────────────────
export function openNewForm(prefill = null) {
  S.editId = null; S.formTags = []; S.formNewImgs = [];
  document.getElementById('form-title').textContent = 'Neues Rezept';
  resetForm();
  if (prefill) fillForm(prefill);
  renderFormImgs();
  document.getElementById('ov-form').classList.add('on');
  document.body.style.overflow = 'hidden';
}

export async function openEditForm(id) {
  try {
    const snap = await api('/api/rezepte/' + id);
    S.editId = snap.id;
    S.current = snap;
    S.formTags = [...(snap.tags||[])];
    S.formNewImgs = [];
    closeOverlay('ov-detail');
    S.current = snap;
    document.getElementById('form-title').textContent = 'Rezept bearbeiten';
    fillForm(snap);
    renderFormImgs();
    document.getElementById('ov-form').classList.add('on');
    document.body.style.overflow = 'hidden';
  } catch(e) { toast(e.message, 'err'); }
}

function resetForm() {
  ['f-titel','f-desc','f-zub','f-url'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  const fp = document.getElementById('f-port'); if (fp) fp.value = 4;
  const fv = document.getElementById('f-zv');   if (fv) fv.value = 0;
  const fk = document.getElementById('f-zk');   if (fk) fk.value = 0;
  const fc = document.getElementById('f-kcal'); if (fc) fc.value = '';
  const fd = document.getElementById('f-diff-form'); if (fd) fd.value = 'mittel';
  const fkt= document.getElementById('f-kat-form');  if (fkt) fkt.value = '';
  renderZRows([]);
  renderFormTags();
}

function fillForm(r) {
  const v = (id, val) => { const el = document.getElementById(id); if (el) el.value = val ?? ''; };
  v('f-titel', r.titel);
  v('f-desc',  r.beschreibung);
  v('f-zub',   r.zubereitung);
  v('f-url',   r.quelle_url);
  v('f-port',  r.portionen || 4);
  v('f-zv',    r.zeit_vorb || 0);
  v('f-zk',    r.zeit_koch || 0);
  v('f-diff-form', r.schwierigkeit || 'mittel');
  v('f-kat-form',  r.kategorie || '');
  v('f-kcal',  r.kalorien_pro_portion || '');
  S.formTags = [...(r.tags||[])];
  renderZRows(r.zutaten||[]);
  renderFormTags();
}

export function renderFormImgs() {
  S.formImgUrls.forEach(u => URL.revokeObjectURL(u));
  S.formImgUrls = S.formNewImgs.map(f => URL.createObjectURL(f));
  const wrap  = document.getElementById('form-imgs');
  if (!wrap) return;
  const exist = S.editId && S.current ? S.current.bilder||[] : [];
  wrap.innerHTML =
    exist.map(b =>
      `<div class="img-thumb"><img src="${x(b.url)}" alt="">
       <button class="img-thumb-del" onclick="delFormExistImg(${b.id})">×</button></div>`
    ).join('') +
    S.formImgUrls.map((url, i) =>
      `<div class="img-thumb"><img src="${url}" alt="">
       <button class="img-thumb-del" onclick="delFormNewImg(${i})">×</button></div>`
    ).join('');
}
window.renderFormImgs = renderFormImgs;

function formImgPicked(e) { S.formNewImgs.push(...Array.from(e.target.files)); renderFormImgs(); e.target.value = ''; }
window.formImgPicked = formImgPicked;
window.delFormNewImg = (i) => { S.formNewImgs.splice(i,1); renderFormImgs(); };
window.delFormExistImg = async (id) => {
  await api('/api/bilder/'+id, {method:'DELETE'}).catch(()=>{});
  if (S.current) S.current.bilder = S.current.bilder.filter(b => b.id !== id);
  renderFormImgs();
};

// ── Ingredient rows ───────────────────────────────────────────────────────────
function initZSortable() {
  const z = document.getElementById('z-form');
  if (!z || !window.Sortable) return;
  if (z.__s) z.__s.destroy();
  z.__s = new Sortable(z, { handle: '.zh', animation: 150, ghostClass: 'zg' });
}

function renderZRows(zs) {
  document.getElementById('z-form').innerHTML = '';
  (zs.length ? zs : [{}]).forEach(z => z.gruppe ? addZGroup(z) : addZRow(z));
  setTimeout(initZSortable, 0);
}

function addZRow(z = {}) {
  const d = document.createElement('div');
  d.className = 'z-row';
  d.innerHTML = `<div class="zh" title="Ziehen">⋮⋮</div>
    <input class="z-inp" placeholder="200" value="${x(z.menge||'')}" data-f="menge">
    <input class="z-inp" placeholder="g"   value="${x(z.einheit||'')}" data-f="einheit">
    <input class="z-inp" placeholder="Mehl" value="${x(z.name||'')}" data-f="name">
    <button class="z-rm" onclick="this.closest('.z-row').remove()" title="Entfernen">×</button>`;
  document.getElementById('z-form').appendChild(d);
}
window.addZRow = addZRow;

function addZGroup(z = {}) {
  const d = document.createElement('div');
  d.className = 'z-group-row';
  d.innerHTML = `<div class="zh" title="Ziehen">⋮⋮</div>
    <input class="z-inp" placeholder="Gruppe, z.B. Für den Teig" value="${x(z.gruppe||'')}" data-f="gruppe">
    <button class="z-rm" onclick="this.closest('.z-group-row').remove()" title="Entfernen">×</button>`;
  document.getElementById('z-form').appendChild(d);
}
window.addZGroup = addZGroup;

function getZRows() {
  return Array.from(document.querySelectorAll('#z-form .z-row, #z-form .z-group-row')).map(r => {
    const g = r.querySelector('[data-f=gruppe]');
    if (g) return { gruppe: g.value.trim() };
    return {
      menge:   r.querySelector('[data-f=menge]').value.trim(),
      einheit: r.querySelector('[data-f=einheit]').value.trim(),
      name:    r.querySelector('[data-f=name]').value.trim()
    };
  }).filter(z => z.name || z.gruppe);
}

// ── Tags ──────────────────────────────────────────────────────────────────────
export function setupTagInp() {
  const inp = document.getElementById('tag-inp');
  if (!inp) return;
  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      const v = inp.value.trim().replace(/,$/, '');
      if (v && !S.formTags.includes(v)) { S.formTags.push(v); renderFormTags(); }
      inp.value = '';
    } else if (e.key === 'Backspace' && !inp.value && S.formTags.length) {
      S.formTags.pop(); renderFormTags();
    }
  });
}

function renderFormTags() {
  const wrap = document.getElementById('tag-wrap');
  const inp  = document.getElementById('tag-inp');
  if (!wrap || !inp) return;
  wrap.innerHTML = S.formTags.map((t, i) =>
    `<span class="tag-edit">${x(t)}<button onclick="S.formTags.splice(${i},1);renderFormTags()">×</button></span>`
  ).join('');
  wrap.appendChild(inp);
}
window.renderFormTags = renderFormTags;

// ── Save form ─────────────────────────────────────────────────────────────────
async function saveForm() {
  const titel = document.getElementById('f-titel')?.value.trim();
  if (!titel) { toast('Bitte Titel eingeben', 'err'); return; }
  const btn = document.querySelector('#ov-form .btn-accent');
  if (btn) btn.disabled = true;
  const payload = {
    titel,
    beschreibung:  document.getElementById('f-desc')?.value.trim(),
    zubereitung:   document.getElementById('f-zub')?.value.trim(),
    quelle_url:    document.getElementById('f-url')?.value.trim(),
    portionen:     parseInt(document.getElementById('f-port')?.value)||4,
    zeit_vorb:     parseInt(document.getElementById('f-zv')?.value)||0,
    zeit_koch:     parseInt(document.getElementById('f-zk')?.value)||0,
    schwierigkeit: document.getElementById('f-diff-form')?.value,
    kategorie:     document.getElementById('f-kat-form')?.value,
    kalorien_pro_portion: parseInt(document.getElementById('f-kcal')?.value) || null,
    zutaten:       getZRows(),
    tags:          S.formTags,
    quelle_typ:    S.editId ? (S.current?.quelle_typ||'manuell') : 'manuell'
  };
  try {
    let r = S.editId
      ? await api('/api/rezepte/'+S.editId, { method:'PUT',  body: JSON.stringify(payload) })
      : await api('/api/rezepte',           { method:'POST', body: JSON.stringify(payload) });
    for (const f of S.formNewImgs) {
      const fd = new FormData();
      fd.append('file', f);
      fd.append('ist_haupt', (r.bilder.length === 0).toString());
      await apiFetch('/api/rezepte/'+r.id+'/bilder', { method:'POST', body: fd }).catch(()=>{});
    }
    toast(S.editId ? 'Gespeichert ✓' : 'Rezept erstellt ✓', 'ok');
    const savedId = r.id;
    const wasNew  = !S.editId;
    closeOverlay('ov-form');
    loadGrid(); loadTags();
    if (wasNew) {
      apiFetch('/api/rezepte/'+savedId+'/fetch-bild', { method:'POST' })
        .then(d => { if (!d.skipped) { loadGrid(); toast('🖼️ Bild hinzugefügt', 'ok'); } })
        .catch(()=>{});
    }
  } catch(e) { toast('Fehler: ' + e.message, 'err'); }
  finally { if (btn) btn.disabled = false; }
}
window.saveForm = saveForm;

// ── Clipboard paste into form ─────────────────────────────────────────────────
export function setupClipboardPaste() {
  document.addEventListener('paste', (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    const imageItem = Array.from(items).find(item => item.type.startsWith('image/'));
    if (!imageItem) return;

    const filePanelOn  = document.getElementById('panel-file')?.classList.contains('on');
    const formOpen     = document.getElementById('ov-form')?.classList.contains('on');

    if (filePanelOn) {
      e.preventDefault();
      const blob = imageItem.getAsFile();
      if (blob) {
        const named = new File([blob], `screenshot-${Date.now()}.png`, { type: 'image/png' });
        import('./import.js').then(m => m.setImportFile(named));
        const hint = document.getElementById('paste-hint');
        if (hint) { hint.classList.add('paste-active'); setTimeout(() => hint.classList.remove('paste-active'), 1500); }
        toast('📋 Screenshot eingefügt', 'ok');
      }
    } else if (formOpen) {
      e.preventDefault();
      const blob = imageItem.getAsFile();
      if (blob) {
        S.formNewImgs.push(new File([blob], `screenshot-${Date.now()}.png`, { type: 'image/png' }));
        renderFormImgs();
        toast('📋 Screenshot zum Rezept hinzugefügt', 'ok');
      }
    }
  });
}
