import { api, apiFetch } from '../api.js';
import { toast, x, EM, scaleAmount, STAR_LABELS, renderDetailStars, renderCardStars, starLabel } from '../utils.js';
import { S } from '../app.js';
import { loadGrid } from './home.js';
import { openEditForm } from './form.js';

let portionState = { base: 4, current: 4 };

export async function openDetail(id) {
  try {
    S.current = await api('/api/rezepte/' + id);
    renderDetail(S.current);
    document.getElementById('ov-detail').classList.add('on');
    document.body.style.overflow = 'hidden';
    const slug = S.current.slug || S.current.id;
    history.pushState({ rezeptId: id }, S.current.titel, '/rezept/' + slug);
  } catch(e) { toast(e.message, 'err'); }
}

export function renderDetail(r) {
  const em   = EM[r.kategorie] || '🍽️';
  const hero = document.getElementById('d-hero');
  hero.querySelectorAll('img.d-hero-img').forEach(i => i.remove());
  const emojiEl = document.getElementById('d-emoji');
  const grad    = document.getElementById('d-grad');
  emojiEl.textContent = em;
  const mainBild = r.haupt_bild || r.bilder?.[0]?.url;
  if (mainBild) {
    emojiEl.style.display = 'none';
    const img = Object.assign(document.createElement('img'), {
      src: mainBild, className: 'd-hero-img', alt: r.titel
    });
    img.onerror = () => { img.remove(); grad.style.display = 'none'; emojiEl.style.display = ''; };
    hero.prepend(img);
    grad.style.display = '';
  } else {
    emojiEl.style.display = '';
    grad.style.display = 'none';
  }
  portionState.base    = r.portionen || 4;
  portionState.current = r.portionen || 4;
  renderThumbs(r);
  buildDetailBody(r);
}

function buildDetailBody(r) {
  const gz   = (r.zeit_vorb||0) + (r.zeit_koch||0);
  const tags = (r.tags||[]).map(t =>
    `<span class="tag-pill" onclick="filterByTag('${x(t)}')">${x(t)}</span>`
  ).join('');
  const src = r.quelle_url
    ? `<a class="source-link" href="${x(r.quelle_url)}" target="_blank" rel="noopener">
        <span class="material-symbols-outlined">open_in_new</span>
        Originalquelle (${x(r.quelle_typ||'Web')})</a>` : '';
  const portionenBar = (r.portionen||0) > 0 ? `
    <div class="portion-bar">
      <span class="portion-label">Portionen</span>
      <div class="portion-ctrl">
        <button class="portion-btn" onclick="scalePortion(-1)">−</button>
        <span class="portion-val" id="portion-val">${portionState.current}</span>
        <button class="portion-btn" onclick="scalePortion(+1)">+</button>
      </div>
      <span class="portion-base">Original: ${portionState.base}</span>
    </div>` : '';

  document.getElementById('d-body').innerHTML = `
    ${r.kategorie ? `<div class="d-category">${x(r.kategorie)}</div>` : ''}
    <h2 class="d-title">${x(r.titel)}</h2>
    <div class="d-meta">
      ${gz ? `<span class="d-meta-pill"><span class="material-symbols-outlined">schedule</span>${gz} Min.</span>` : ''}
      ${r.portionen ? `<span class="d-meta-pill" id="meta-portionen"><span class="material-symbols-outlined">group</span>${r.portionen} Portionen</span>` : ''}
      ${r.kalorien_pro_portion ? `<span class="d-meta-pill" id="meta-kalorien"><span class="material-symbols-outlined">local_fire_department</span>${r.kalorien_pro_portion} kcal<small style="font-weight:400;opacity:0.7;font-size:0.85em"> / Port.</small></span>` : ''}
      ${r.zeit_vorb ? `<span class="d-meta-pill">Vorb. ${r.zeit_vorb} Min.</span>` : ''}
      ${r.schwierigkeit ? `<span class="diff-tag ${x(r.schwierigkeit)}" style="margin:0">${x(r.schwierigkeit)}</span>` : ''}
    </div>
    ${r.beschreibung ? `<p class="d-desc">${x(r.beschreibung)}</p>` : ''}
    ${src ? `<div style="margin-bottom:1.25rem">${src}</div>` : ''}
    <div class="star-row">
      <span class="star-row-label">Bewertung</span>
      <div class="stars" id="detail-stars">${renderDetailStars(r.bewertung, r.id)}</div>
      <span class="star-hint" id="star-hint">${r.bewertung ? starLabel(r.bewertung) : 'Tippen zum Bewerten'}</span>
    </div>
    <div class="detail-actions">
      <button class="act-btn" onclick="shareRezept()" id="btn-share">
        <span class="material-symbols-outlined">share</span>Teilen
      </button>
      <button class="act-btn" onclick="copyZutaten()" id="btn-copy">
        <span class="material-symbols-outlined">shopping_cart</span>Einkaufsliste
      </button>
      <button class="act-btn" onclick="exportPDF()">
        <span class="material-symbols-outlined">picture_as_pdf</span>PDF
      </button>
    </div>
    ${portionenBar}
    ${(r.zutaten||[]).length ? `
      <div class="d-section-title">Zutaten</div>
      <ul class="ingredients" id="ing-list">${renderIngredients(r.zutaten, portionState.current, portionState.base)}</ul>` : ''}
    ${r.zubereitung ? `<div class="d-section-title">Zubereitung</div><div class="steps"><p class="step-text">${x(r.zubereitung)}</p></div>` : ''}
    ${tags ? `<div class="d-section-title">Tags</div><div class="tags-row">${tags}</div>` : ''}
  `;
}

function renderIngredients(zutaten, current, base) {
  const factor = base > 0 ? current / base : 1;
  return zutaten.map(z => {
    if (z.gruppe) return `<li class="ing-group-header">${x(z.gruppe)}</li>`;
    const scaled   = scaleAmount(z.menge || '', factor);
    const copyText = [scaled, x(z.einheit||''), x(z.name)].filter(Boolean).join(' ');
    return `<li class="ing-row">
      <span class="ing-amount">${scaled} ${x(z.einheit||'')}</span>
      <span class="ing-name">${x(z.name)}</span>
      <button class="ing-copy" onclick="copyZutat(this,'${copyText.replace(/'/g,"&#39;")}')">
        <span class="material-symbols-outlined">content_copy</span>
      </button>
    </li>`;
  }).join('');
}

function scalePortion(delta) {
  portionState.current = Math.max(1, portionState.current + delta);
  document.getElementById('portion-val').textContent = portionState.current;
  const mp = document.getElementById('meta-portionen');
  if (mp) mp.innerHTML = `<span class="material-symbols-outlined">group</span>${portionState.current} Portionen`;
  const ingList = document.getElementById('ing-list');
  if (ingList && S.current?.zutaten) {
    ingList.innerHTML = renderIngredients(S.current.zutaten, portionState.current, portionState.base);
  }
}
window.scalePortion = scalePortion;

// ── Bewertung ─────────────────────────────────────────────────────────────────
async function setBewertung(rid, sterne) {
  const current = S.current?.bewertung || 0;
  const newVal  = current === sterne ? null : sterne;
  try {
    await api('/api/rezepte/' + rid + '/bewertung', {
      method: 'PATCH', body: JSON.stringify({ sterne: newVal })
    });
    if (S.current) S.current.bewertung = newVal;
    document.getElementById('detail-stars').innerHTML = renderDetailStars(newVal, rid);
    const hint = document.getElementById('star-hint');
    if (hint) hint.textContent = newVal ? starLabel(newVal) : 'Tippen zum Bewerten';
    const rezept = S.rezepte?.find(r => r.id === rid);
    if (rezept) {
      rezept.bewertung = newVal;
      const card = document.querySelector(`#grid .card[data-id="${rid}"]`);
      if (card) {
        const starDiv = card.querySelector('.card-stars');
        if (newVal) {
          const ns = document.createElement('div');
          ns.innerHTML = renderCardStars(newVal);
          if (starDiv) starDiv.replaceWith(ns.firstChild);
          else card.querySelector('.card-body').insertAdjacentHTML('beforeend', renderCardStars(newVal));
        } else if (starDiv) {
          starDiv.remove();
        }
      }
    }
    toast(newVal ? '⭐'.repeat(newVal) + ' – ' + starLabel(newVal) : 'Bewertung entfernt', 'ok');
  } catch(e) { toast('Fehler: ' + e.message, 'err'); }
}
window.setBewertung = setBewertung;

function previewStars(n) {
  document.querySelectorAll('#detail-stars .star').forEach((el, i) => {
    el.textContent = i < n ? '★' : '☆';
    el.className = 'star ' + (i < n ? 'filled' : 'empty');
  });
  const hint = document.getElementById('star-hint');
  if (hint) hint.textContent = starLabel(n);
}
window.previewStars = previewStars;

function resetStarPreview(rid, bewertung) {
  document.querySelectorAll('#detail-stars .star').forEach((el, i) => {
    el.textContent = i < bewertung ? '★' : '☆';
    el.className = 'star ' + (i < bewertung ? 'filled' : 'empty');
  });
  const hint = document.getElementById('star-hint');
  if (hint) hint.textContent = bewertung ? starLabel(bewertung) : 'Tippen zum Bewerten';
}
window.resetStarPreview = resetStarPreview;

// ── Actions ───────────────────────────────────────────────────────────────────
function copyZutaten() {
  if (!S.current?.zutaten?.length) return;
  const factor = portionState.base > 0 ? portionState.current / portionState.base : 1;
  const lines = [
    `🛒 ${S.current.titel} (${portionState.current} Portionen)`, '',
    ...S.current.zutaten.map(z => {
      if (z.gruppe) return `\n▸ ${z.gruppe}`;
      const m = scaleAmount(z.menge||'', factor);
      return `• ${[m, z.einheit||'', z.name].filter(Boolean).join(' ')}`;
    })
  ];
  navigator.clipboard.writeText(lines.join('\n')).then(() => {
    const btn = document.getElementById('btn-copy');
    btn.classList.add('copied');
    btn.innerHTML = `<span class="material-symbols-outlined">check</span> Kopiert!`;
    setTimeout(() => {
      btn.classList.remove('copied');
      btn.innerHTML = `<span class="material-symbols-outlined">shopping_cart</span>Einkaufsliste`;
    }, 2500);
  }).catch(() => toast('Kopieren fehlgeschlagen', 'err'));
}
window.copyZutaten = copyZutaten;

function copyZutat(btn, text) {
  navigator.clipboard.writeText(text).then(() => {
    btn.classList.add('done');
    btn.innerHTML = '<span class="material-symbols-outlined">check</span>';
    setTimeout(() => {
      btn.classList.remove('done');
      btn.innerHTML = '<span class="material-symbols-outlined">content_copy</span>';
    }, 1800);
  }).catch(() => toast('Kopieren fehlgeschlagen', 'err'));
}
window.copyZutat = copyZutat;

async function shareRezept() {
  if (!S.current) return;
  const r    = S.current;
  const slug = r.slug || r.id;
  const url  = window.location.origin + '/rezept/' + slug;
  const gz   = (r.zeit_vorb||0) + (r.zeit_koch||0);
  const text = r.beschreibung || [r.kategorie, gz ? gz+' Min.' : null, r.schwierigkeit].filter(Boolean).join(' · ');
  if (navigator.share) {
    try { await navigator.share({ title: r.titel, text, url }); return; }
    catch(e) { if (e.name === 'AbortError') return; }
  }
  try {
    await navigator.clipboard.writeText(url);
    const btn = document.getElementById('btn-share');
    btn.classList.add('share-ok');
    btn.innerHTML = '<span class="material-symbols-outlined">check</span> Link kopiert!';
    setTimeout(() => {
      btn.classList.remove('share-ok');
      btn.innerHTML = '<span class="material-symbols-outlined">share</span>Teilen';
    }, 2500);
  } catch { toast('Link: ' + url, ''); }
}
window.shareRezept = shareRezept;

function exportPDF() {
  if (!S.current) return;
  const r      = S.current;
  const factor = portionState.base > 0 ? portionState.current / portionState.base : 1;
  const gz     = (r.zeit_vorb||0) + (r.zeit_koch||0);
  const meta   = [r.kategorie, gz ? gz+' Min.' : null, portionState.current+' Portionen', r.schwierigkeit].filter(Boolean).join(' · ');
  const ings   = (r.zutaten||[]).map(z => z.gruppe
    ? '<div class="print-ing print-ing-group">' + x(z.gruppe) + '</div>'
    : '<div class="print-ing"><span class="print-ing-amt">' + scaleAmount(z.menge||'', factor) + ' ' + x(z.einheit||'') + '</span><span>' + x(z.name) + '</span></div>'
  ).join('');
  const bildUrl = r.haupt_bild || r.bilder?.[0]?.url;
  const bildHtml = bildUrl ? `<img class="print-img" src="${window.location.origin}${bildUrl}" alt="">` : '';
  const today  = new Date().toLocaleDateString('de-AT');
  let area = document.getElementById('print-area');
  if (!area) { area = document.createElement('div'); area.id = 'print-area'; document.body.appendChild(area); }
  area.innerHTML = bildHtml +
    '<div class="print-title">' + x(r.titel) + '</div>' +
    '<div class="print-meta">' + meta + '</div>' +
    (r.beschreibung ? '<div class="print-desc">' + x(r.beschreibung) + '</div>' : '') +
    (ings ? '<div class="print-sect">Zutaten</div>' + ings : '') +
    (r.zubereitung ? '<div class="print-sect">Zubereitung</div><div class="print-steps">' + x(r.zubereitung) + '</div>' : '') +
    '<div class="print-footer">Rezeptify Familie Battlogg · ' + today + (r.quelle_url ? ' · ' + r.quelle_url : '') + '</div>';
  const oldTitle = document.title;
  document.title = r.titel;
  const img = area.querySelector('img.print-img');
  const doPrint = () => { window.print(); document.title = oldTitle; };
  if (img && !img.complete) { img.onload = doPrint; img.onerror = doPrint; }
  else doPrint();
}
window.exportPDF = exportPDF;

// ── Thumbnail strip ───────────────────────────────────────────────────────────
function renderThumbs(r) {
  const wrap = document.getElementById('thumb-strip-wrap');
  if (!r.bilder?.length) { wrap.innerHTML = ''; return; }
  wrap.innerHTML = `<div class="thumb-strip">
    ${r.bilder.map(b =>
      `<div class="thumb-item ${b.ist_haupt ? 'on' : ''}" onclick="switchThumb('${x(b.url)}',${b.id},this)">
        <img src="${x(b.url)}" alt="" loading="lazy">
        <button class="thumb-del" onclick="delThumb(event,${b.id})">×</button>
      </div>`).join('')}
    <div class="thumb-add" title="Aus Galerie" onclick="this.querySelector('input').click()">
      <input type="file" accept="image/*" onchange="uploadThumb(event)" style="display:none">
      <span class="material-symbols-outlined">photo_library</span>
    </div>
    <div class="thumb-add" title="Kamerafoto" onclick="this.querySelector('input').click()">
      <input type="file" accept="image/*" capture="environment" onchange="uploadThumb(event)" style="display:none">
      <span class="material-symbols-outlined">photo_camera</span>
    </div>
  </div>`;
}

function switchThumb(url, id, el) {
  document.getElementById('d-hero').querySelectorAll('img.d-hero-img').forEach(i => i.remove());
  const emojiEl = document.getElementById('d-emoji');
  emojiEl.style.opacity = '0';
  const img = Object.assign(document.createElement('img'), { src: url, className: 'd-hero-img' });
  document.getElementById('d-hero').prepend(img);
  document.getElementById('d-grad').style.display = '';
  document.querySelectorAll('.thumb-item').forEach(t => t.classList.remove('on'));
  el.classList.add('on');
  api('/api/bilder/' + id + '/haupt', { method: 'PUT' }).catch(() => {});
}
window.switchThumb = switchThumb;

async function delThumb(e, id) {
  e.stopPropagation();
  if (!confirm('Bild löschen?')) return;
  await api('/api/bilder/' + id, { method: 'DELETE' }).catch(err => toast(err.message, 'err'));
  S.current = await api('/api/rezepte/' + S.current.id);
  renderDetail(S.current);
  toast('Bild gelöscht', 'ok');
}
window.delThumb = delThumb;

async function uploadThumb(e) {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData();
  fd.append('file', f);
  fd.append('ist_haupt', (!S.current.bilder?.length).toString());
  await apiFetch('/api/rezepte/' + S.current.id + '/bilder', { method: 'POST', body: fd });
  S.current = await api('/api/rezepte/' + S.current.id);
  renderDetail(S.current);
  toast('Bild hinzugefügt ✓', 'ok');
}
window.uploadThumb = uploadThumb;

// ── Delete / edit ─────────────────────────────────────────────────────────────
async function deleteCurrent() {
  if (!S.current || !confirm(`"${S.current.titel}" löschen?`)) return;
  await api('/api/rezepte/' + S.current.id, { method: 'DELETE' });
  toast('Rezept gelöscht', 'ok');
  closeOverlay('ov-detail');
  loadGrid();
}
window.deleteCurrent = deleteCurrent;

function editCurrent() {
  if (!S.current) return;
  openEditForm(S.current.id);
}
window.editCurrent = editCurrent;

// ── Overlay ───────────────────────────────────────────────────────────────────
export function closeOverlay(id) {
  document.getElementById(id)?.classList.remove('on');
  document.body.style.overflow = '';
  if (id === 'ov-detail') {
    S.current = null;
    if (window.location.pathname.startsWith('/rezept/')) history.pushState({}, document.title, '/');
  }
  if (id === 'ov-form') {
    S.editId = null;
    S.formNewImgs = [];
    S.formImgUrls.forEach(u => URL.revokeObjectURL(u));
    S.formImgUrls = [];
    S.current = null;
  }
}
window.closeOverlay = closeOverlay;
window.overlayClick = (e, id) => { if (e.target === document.getElementById(id)) closeOverlay(id); };
window.openDetail = openDetail;
