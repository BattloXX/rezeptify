import { api } from '../api.js';
import { toast, x, EM } from '../utils.js';

const RB = { selected: [], allRezepte: [], dragSrc: null };

export function initBuch() {
  window.rbFilter    = rbFilter;
  window.rbSelectAll = rbSelectAll;
  window.rbClearAll  = rbClearAll;
  window.rbAdd       = rbAdd;
  window.rbRemove    = rbRemove;
  window.rbDragStart = rbDragStart;
  window.rbDragOver  = rbDragOver;
  window.rbDrop      = rbDrop;
  window.rbDragEnd   = rbDragEnd;
  window.exportRezeptbuch = exportRezeptbuch;
  _load();
}

async function _load() {
  if (RB.allRezepte.length) { renderRbAvail(); return; }
  const data = await api('/api/rezepte?limit=200').catch(() => null);
  if (!data) return;
  RB.allRezepte = data.items;
  const yr = document.getElementById('rb-jahr');
  if (yr && !yr.value) yr.value = new Date().getFullYear();
  renderRbAvail();
}

function rbFilter() {
  renderRbAvail((document.getElementById('rb-search')?.value||'').toLowerCase());
}

function renderRbAvail(filter = '') {
  const list   = document.getElementById('rb-avail-list');
  if (!list) return;
  const selIds = new Set(RB.selected.map(r => r.id));
  const items  = RB.allRezepte.filter(r =>
    !selIds.has(r.id) &&
    (r.titel.toLowerCase().includes(filter) || (r.kategorie||'').toLowerCase().includes(filter))
  );
  const cnt = document.getElementById('rb-avail-count');
  if (cnt) cnt.textContent = items.length;
  list.innerHTML = items.length ? items.map(r => {
    const em    = EM[r.kategorie] || '🍴';
    const img   = r.haupt_bild || r.bilder?.[0]?.url;
    const thumb = img ? `<div class="rb-item-thumb"><img src="${x(img)}" alt=""></div>` : `<div class="rb-item-thumb">${em}</div>`;
    const gz    = (r.zeit_vorb||0)+(r.zeit_koch||0);
    return `<li class="rb-item" onclick="rbAdd(${r.id})">
      ${thumb}
      <div class="rb-item-info">
        <div class="rb-item-title">${x(r.titel)}</div>
        <div class="rb-item-meta">${x(r.kategorie||'')}${gz?' · '+gz+' min':''}</div>
      </div>
      <button class="rb-item-add" onclick="event.stopPropagation();rbAdd(${r.id})">+</button>
    </li>`;
  }).join('') : `<li class="rb-empty">Keine Rezepte gefunden</li>`;
}

function renderRbSelected() {
  const list = document.getElementById('rb-sel-list');
  const btn  = document.getElementById('rb-export-btn');
  const cnt  = document.getElementById('rb-sel-count');
  if (!list) return;
  if (cnt) cnt.textContent = RB.selected.length + ' Rezepte';
  if (btn) btn.disabled = RB.selected.length === 0;
  if (!RB.selected.length) {
    list.innerHTML = '<li class="rb-empty">Noch keine Rezepte ausgewählt.<br>Links auf + klicken.</li>';
    return;
  }
  list.innerHTML = RB.selected.map((r, i) => {
    const em    = EM[r.kategorie] || '🍴';
    const img   = r.haupt_bild || r.bilder?.[0]?.url;
    const thumb = img ? `<div class="rb-sel-thumb"><img src="${x(img)}" alt=""></div>` : `<div class="rb-sel-thumb">${em}</div>`;
    return `<li class="rb-sel-item" draggable="true"
      ondragstart="rbDragStart(event,${i})" ondragover="rbDragOver(event,${i})"
      ondrop="rbDrop(event,${i})" ondragend="rbDragEnd()">
      <span class="rb-drag-handle"><span class="material-symbols-outlined">drag_indicator</span></span>
      <span class="rb-sel-num">${i+1}</span>
      ${thumb}
      <span class="rb-sel-title">${x(r.titel)}</span>
      <button class="rb-sel-remove" onclick="rbRemove(${r.id})">×</button>
    </li>`;
  }).join('');
}

function rbAdd(id) {
  const r = RB.allRezepte.find(r => r.id === id);
  if (!r || RB.selected.find(s => s.id === id)) return;
  RB.selected.push(r);
  renderRbSelected();
  renderRbAvail((document.getElementById('rb-search')?.value||'').toLowerCase());
}
function rbRemove(id) {
  RB.selected = RB.selected.filter(r => r.id !== id);
  renderRbSelected();
  renderRbAvail((document.getElementById('rb-search')?.value||'').toLowerCase());
}
function rbClearAll()  { RB.selected = []; renderRbSelected(); renderRbAvail(); }
function rbSelectAll() {
  RB.allRezepte.forEach(r => { if (!RB.selected.find(s => s.id === r.id)) RB.selected.push(r); });
  renderRbSelected(); renderRbAvail();
}
function rbDragStart(e, i) { RB.dragSrc = i; e.dataTransfer.effectAllowed = 'move'; e.currentTarget.classList.add('dragging'); }
function rbDragOver(e, i)  { e.preventDefault(); document.querySelectorAll('.rb-sel-item').forEach(el => el.classList.remove('drag-over')); e.currentTarget.classList.add('drag-over'); }
function rbDrop(e, i)      { e.preventDefault(); if (RB.dragSrc===null||RB.dragSrc===i) return; const m = RB.selected.splice(RB.dragSrc,1)[0]; RB.selected.splice(i,0,m); RB.dragSrc=null; renderRbSelected(); }
function rbDragEnd()       { document.querySelectorAll('.rb-sel-item').forEach(el => el.classList.remove('dragging','drag-over')); RB.dragSrc = null; }

async function exportRezeptbuch() {
  if (!RB.selected.length) return;
  const titel      = document.getElementById('rb-titel')?.value || 'Rezeptbuch';
  const untertitel = document.getElementById('rb-untertitel')?.value || '';
  const autor      = document.getElementById('rb-autor')?.value || '';
  const jahr       = document.getElementById('rb-jahr')?.value || new Date().getFullYear();
  toast('Lade Rezeptdaten …', '');
  const rezepte = await Promise.all(RB.selected.map(r => api('/api/rezepte/' + r.id).catch(() => r)));
  const area    = document.getElementById('rb-print-area');

  const coverHtml = `<div class="rb-cover">
    <div class="rb-cover-inner">
      <div class="rb-cover-icon">🌿</div>
      <h1 class="rb-cover-title">${x(titel)}</h1>
      ${untertitel ? `<p class="rb-cover-sub">${x(untertitel)}</p>` : ''}
      <div class="rb-cover-divider"></div>
      ${autor ? `<p class="rb-cover-autor">${x(autor)}</p>` : ''}
      ${jahr  ? `<p class="rb-cover-jahr">${x(String(jahr))}</p>` : ''}
    </div>
  </div>`;

  const tocRows = rezepte.map((r, i) => {
    const gz = (r.zeit_vorb||0)+(r.zeit_koch||0);
    return `<tr class="rb-toc-row">
      <td class="rb-toc-num">${i+1}</td>
      <td class="rb-toc-name">${x(r.titel)}</td>
      <td class="rb-toc-cat">${x(r.kategorie||'')}</td>
      <td class="rb-toc-time">${gz ? gz+' min' : '—'}</td>
    </tr>`;
  }).join('');
  const tocHtml = `<div class="rb-toc rb-page-break">
    <h2 class="rb-sect-h">Inhaltsverzeichnis</h2>
    <table class="rb-toc-table">
      <thead><tr><th style="width:32px">#</th><th>Rezept</th><th style="width:100px">Kategorie</th><th style="width:60px">Zeit</th></tr></thead>
      <tbody>${tocRows}</tbody>
    </table>
  </div>`;

  const recipePagesHtml = rezepte.map((r, i) => {
    const gz      = (r.zeit_vorb||0)+(r.zeit_koch||0);
    const meta    = [r.kategorie, gz ? gz+' Min.' : null, r.portionen ? r.portionen+' Port.' : null, r.schwierigkeit, r.kalorien_pro_portion ? r.kalorien_pro_portion+' kcal/P.' : null].filter(Boolean).join(' · ');
    const imgUrl  = r.haupt_bild || r.bilder?.[0]?.url;
    const imgHtml = imgUrl ? `<img class="rb-recipe-img" src="${window.location.origin}${imgUrl}" alt="${x(r.titel)}">` : '';
    const ings    = (r.zutaten||[]).map(z => z.gruppe
      ? `<tr><td colspan="2" class="rb-ing-group">${x(z.gruppe)}</td></tr>`
      : `<tr><td class="rb-ing-amt">${x(z.menge||'')} ${x(z.einheit||'')}</td><td>${x(z.name)}</td></tr>`
    ).join('');
    const tags    = (r.tags||[]).length ? `<div class="rb-tags">${(r.tags||[]).map(t=>`<span class="rb-tag">${x(t)}</span>`).join('')}</div>` : '';
    const src     = r.quelle_url ? `<div class="rb-src">Quelle: ${x(r.quelle_url)}</div>` : '';
    return `<div class="rb-recipe rb-page-break">
      <div class="rb-recipe-hdr">
        <span class="rb-recipe-num">${i+1}</span>
        <div>
          ${r.kategorie ? `<div class="rb-recipe-kat">${x(r.kategorie)}</div>` : ''}
          <h2 class="rb-recipe-title">${x(r.titel)}</h2>
          <div class="rb-recipe-meta">${meta}</div>
        </div>
      </div>
      ${imgHtml}
      ${r.beschreibung ? `<p class="rb-recipe-desc">${x(r.beschreibung)}</p>` : ''}
      ${ings ? `<h3 class="rb-sub-h">Zutaten</h3><table class="rb-ing-table">${ings}</table>` : ''}
      ${r.zubereitung ? `<h3 class="rb-sub-h">Zubereitung</h3><div class="rb-steps">${x(r.zubereitung)}</div>` : ''}
      ${tags}${src}
    </div>`;
  }).join('');

  const css = `<style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:Georgia,serif;font-size:11pt;color:#1a1a1a;line-height:1.65}
    @page{size:A4;margin:2cm 2.2cm}
    .rb-cover{height:100vh;display:flex;align-items:center;justify-content:center;text-align:center;background:#1c1b1b;color:white;page-break-after:always;break-after:page}
    .rb-cover-inner{padding:3cm}.rb-cover-icon{font-size:4rem;margin-bottom:1.5cm}
    .rb-cover-title{font-size:28pt;font-weight:700;line-height:1.2;margin-bottom:.5cm}
    .rb-cover-sub{font-size:14pt;color:rgba(255,255,255,.6);margin-bottom:1cm;font-style:italic}
    .rb-cover-divider{width:4cm;height:2px;background:#e8823a;margin:1cm auto}
    .rb-cover-autor{font-size:12pt;color:rgba(255,255,255,.7);margin-bottom:.3cm}
    .rb-cover-jahr{font-size:10pt;color:rgba(255,255,255,.4)}
    .rb-page-break{page-break-before:always}
    .rb-sect-h{font-size:18pt;font-weight:700;margin-bottom:.8cm;border-bottom:2pt solid #e8823a;padding-bottom:.3cm}
    .rb-toc-table{width:100%;border-collapse:collapse;font-size:10.5pt}
    .rb-toc-table thead th{text-align:left;font-size:8pt;text-transform:uppercase;letter-spacing:.5px;color:#888;border-bottom:1pt solid #ddd;padding:0 0 6pt}
    .rb-toc-row td{padding:7pt 0;border-bottom:.5pt solid #eee;vertical-align:middle}
    .rb-toc-num{color:#e8823a;font-weight:700;font-size:9pt;padding-right:10pt!important}
    .rb-toc-name{font-weight:600}.rb-toc-cat,.rb-toc-time{color:#888;font-size:9.5pt}
    .rb-recipe-hdr{display:flex;align-items:flex-start;gap:14pt;margin-bottom:.5cm}
    .rb-recipe-num{background:#e8823a;color:white;border-radius:50%;width:32pt;height:32pt;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:11pt;flex-shrink:0;margin-top:4pt}
    .rb-recipe-kat{font-size:7.5pt;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#e8823a;margin-bottom:3pt}
    .rb-recipe-title{font-size:20pt;font-weight:700;line-height:1.2;margin-bottom:5pt}
    .rb-recipe-meta{font-size:9pt;color:#666}.rb-recipe-img{width:100%;max-height:8cm;object-fit:cover;border-radius:4pt;margin:.4cm 0;page-break-inside:avoid}
    .rb-recipe-desc{font-style:italic;color:#555;margin-bottom:.5cm;font-size:10.5pt;line-height:1.6}
    .rb-sub-h{font-size:12pt;font-weight:700;margin:.5cm 0 .25cm}
    .rb-ing-table{width:100%;border-collapse:collapse;font-size:10pt;margin-bottom:.4cm}
    .rb-ing-table tr{border-bottom:.5pt solid #eee;page-break-inside:avoid}
    .rb-ing-table td{padding:4pt 0}.rb-ing-amt{font-weight:700;color:#e8823a;width:100pt}
    .rb-ing-group{font-size:8pt;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#e8823a;padding:8pt 0 3pt!important;border-bottom:none!important}
    .rb-steps{font-size:10.5pt;line-height:1.8;white-space:pre-wrap;color:#333;margin-bottom:.4cm}
    .rb-tags{display:flex;flex-wrap:wrap;gap:4pt;margin-top:.3cm}
    .rb-tag{background:#f0f0f0;border-radius:20pt;padding:2pt 8pt;font-size:8pt;color:#666}
    .rb-src{font-size:8pt;color:#aaa;margin-top:.3cm}
  </style>`;

  area.innerHTML = css + coverHtml + tocHtml + recipePagesHtml;
  const popup = window.open('', '_blank', 'width=900,height=700');
  if (!popup) { toast('Popup wurde blockiert', 'err'); return; }
  popup.document.write(`<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8"><title>${x(titel)}</title>${css}</head><body>${coverHtml}${tocHtml}${recipePagesHtml}</body></html>`);
  popup.document.close();
  popup.onload = () => {
    const imgs = popup.document.querySelectorAll('img');
    if (!imgs.length) { popup.print(); return; }
    let loaded = 0;
    const tryPrint = () => { if (++loaded >= imgs.length) popup.print(); };
    imgs.forEach(img => { if (img.complete) tryPrint(); else { img.onload = tryPrint; img.onerror = tryPrint; } });
  };
  setTimeout(() => { try { popup.print(); } catch(e) {} }, 3000);
}
