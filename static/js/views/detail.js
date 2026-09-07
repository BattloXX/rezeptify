import { api, apiFetch } from '../api.js';
import { toast, x, EM, optimisticToggle, scaleAmount, shareText, STAR_LABELS, renderDetailStars, renderCardStars, starLabel } from '../utils.js';
import { S } from '../app.js';
import { loadGrid } from './home.js';
import { openEditForm } from './form.js';
import { startKochmodus } from './kochmodus.js';

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
  const quelldatei = r.quelldatei
    ? `<a class="source-link" href="/static/uploads/${x(r.quelldatei)}" target="_blank"
          style="margin-left:${r.quelle_url ? '8px' : '0'}">
        <span class="material-symbols-outlined">${r.quelldatei.endsWith('.pdf') ? 'picture_as_pdf' : 'image'}</span>
        Quelldatei ${r.quelldatei.endsWith('.pdf') ? '(PDF)' : '(Bild)'}</a>` : '';
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
    ${(src || quelldatei) ? `<div style="margin-bottom:1.25rem;display:flex;flex-wrap:wrap;gap:8px">${src}${quelldatei}</div>` : ''}
    <div class="star-row">
      <span class="star-row-label">Bewertung</span>
      <div class="stars" id="detail-stars">${renderDetailStars(r.bewertung, r.id)}</div>
      <span class="star-hint" id="star-hint">${r.bewertung ? starLabel(r.bewertung) : 'Tippen zum Bewerten'}</span>
      <button class="detail-favorite${r.favorit ? ' on' : ''}" id="detail-favorite" onclick="toggleDetailFavorite()" aria-label="${r.favorit ? 'Favorit entfernen' : 'Als Favorit markieren'}">${r.favorit ? '♥' : '♡'}</button>
    </div>
    <div class="cook-history" id="cook-history">${renderCookHistory(r)}</div>
    <div class="detail-actions">
      <button class="act-btn act-btn-cook" onclick="startKochmodus(${r.id})">
        <span class="material-symbols-outlined">skillet</span>Jetzt kochen
      </button>
      <button class="act-btn" onclick="shareRezept()" id="btn-share">
        <span class="material-symbols-outlined">share</span>Teilen
      </button>
      <button class="act-btn" onclick="copyZutaten()" id="btn-copy">
        <span class="material-symbols-outlined">shopping_cart</span>Einkaufsliste
      </button>
      <button class="act-btn" onclick="addToShoppingList()" id="btn-add-shopping">
        <span class="material-symbols-outlined">add_shopping_cart</span>Zur Einkaufsliste hinzufügen
      </button>
      <button class="act-btn" onclick="openPlanOverlay()">
        <span class="material-symbols-outlined">calendar_add_on</span>Für diese Woche planen
      </button>
      <button class="act-btn" onclick="markCookedToday()" id="btn-cooked-today">
        <span class="material-symbols-outlined">restaurant</span>Heute gekocht
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
  const update = (value) => {
    if (S.current) S.current.bewertung = value;
    document.getElementById('detail-stars').innerHTML = renderDetailStars(value, rid);
    const hint = document.getElementById('star-hint');
    if (hint) hint.textContent = value ? starLabel(value) : 'Tippen zum Bewerten';
    const rezept = S.rezepte?.find(r => r.id === rid);
    if (rezept) {
      rezept.bewertung = value;
      const card = document.querySelector(`#grid .card[data-id="${rid}"]`);
      if (card) {
        const starDiv = card.querySelector('.card-stars');
        if (value) {
          const ns = document.createElement('div'); ns.innerHTML = renderCardStars(value);
          if (starDiv) starDiv.replaceWith(ns.firstChild);
          else card.querySelector('.card-body').insertAdjacentHTML('beforeend', renderCardStars(value));
        } else if (starDiv) starDiv.remove();
      }
    }
  };
  try {
    await optimisticToggle({
      apply: () => update(newVal),
      request: () => api('/api/rezepte/' + rid + '/bewertung', { method: 'PATCH', body: JSON.stringify({ sterne: newVal }) }),
      revert: () => update(current),
    });
    toast(newVal ? '⭐'.repeat(newVal) + ' – ' + starLabel(newVal) : 'Bewertung entfernt', 'ok');
  } catch (_) { /* The helper already restored state and showed a toast. */ }
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

function renderCookHistory(r) {
  const last = r.zuletzt_gekocht ? new Date(r.zuletzt_gekocht).toLocaleDateString('de-AT') : 'Noch nicht gekocht';
  return `<span>Zuletzt gekocht: <strong>${last}</strong></span><span>Insgesamt gekocht: <strong>${r.anzahl_gekocht || 0}×</strong></span>`;
}

async function toggleDetailFavorite() {
  if (!S.current) return;
  const old = Boolean(S.current.favorit);
  const update = (value) => {
    S.current.favorit = value;
    const button = document.getElementById('detail-favorite');
    if (button) { button.classList.toggle('on', value); button.textContent = value ? '♥' : '♡'; }
    document.querySelectorAll(`.card[data-id="${S.current.id}"] .card-favorite`).forEach(card => {
      card.classList.toggle('on', value); card.textContent = value ? '♥' : '♡';
    });
    const listRecipe = S.rezepte?.find(r => r.id === S.current.id);
    if (listRecipe) listRecipe.favorit = value;
  };
  try {
    await optimisticToggle({ apply: () => update(!old), request: () => api('/api/rezepte/' + S.current.id + '/favorit', { method: 'PATCH', body: JSON.stringify({ favorit: !old }) }), revert: () => update(old) });
  } catch (_) { /* The helper already restored state and showed a toast. */ }
}
window.toggleDetailFavorite = toggleDetailFavorite;

async function markCookedToday() {
  if (!S.current) return;
  try {
    const result = await api('/api/rezepte/' + S.current.id + '/kochen', { method: 'POST', body: JSON.stringify({}) });
    S.current.zuletzt_gekocht = result.zuletzt_gekocht;
    S.current.anzahl_gekocht = result.anzahl_gekocht;
    const history = document.getElementById('cook-history');
    if (history) history.innerHTML = renderCookHistory(S.current);
    const listRecipe = S.rezepte?.find(r => r.id === S.current.id);
    if (listRecipe) Object.assign(listRecipe, { zuletzt_gekocht: result.zuletzt_gekocht, anzahl_gekocht: result.anzahl_gekocht });
    toast('Als heute gekocht gespeichert', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}
window.markCookedToday = markCookedToday;

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
window.startKochmodus = startKochmodus;

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
  const shared = await shareText(r.titel, `${text ? text + '\n' : ''}${url}`);
  if (shared === 'copied') {
    const btn = document.getElementById('btn-share');
    btn.classList.add('share-ok');
    btn.innerHTML = '<span class="material-symbols-outlined">check</span> Link kopiert!';
    setTimeout(() => {
      btn.classList.remove('share-ok');
      btn.innerHTML = '<span class="material-symbols-outlined">share</span>Teilen';
    }, 2500);
  }
}
window.shareRezept = shareRezept;

async function addToShoppingList() {
  if (!S.current) return;
  const btn = document.getElementById('btn-add-shopping');
  try {
    await api('/api/rezepte/' + S.current.id + '/zu-einkaufsliste', {
      method: 'POST', body: JSON.stringify({ portionen: portionState.current })
    });
    const old = btn.innerHTML;
    btn.innerHTML = '<span class="material-symbols-outlined">check</span> Hinzugefügt!';
    setTimeout(() => { if (btn) btn.innerHTML = old; }, 2500);
  } catch (e) { toast(e.message, 'err'); }
}
window.addToShoppingList = addToShoppingList;

function openPlanOverlay() {
  if (!S.current) return;
  const select = document.getElementById('plan-date');
  const today = new Date(); today.setHours(0, 0, 0, 0);
  select.innerHTML = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(today); d.setDate(today.getDate() + i);
    const value = d.toISOString().slice(0, 10);
    return `<option value="${value}">${d.toLocaleDateString('de-AT', { weekday: 'long', day: '2-digit', month: '2-digit' })}</option>`;
  }).join('');
  document.getElementById('plan-recipe-title').textContent = S.current.titel;
  document.getElementById('ov-planen').classList.add('on');
}

async function confirmPlan() {
  if (!S.current) return;
  try {
    await api('/api/wochenplan', { method: 'POST', body: JSON.stringify({
      rezept_id: S.current.id, datum: document.getElementById('plan-date').value,
      mahlzeit: document.getElementById('plan-meal').value, portionen: portionState.current,
    }) });
    closeOverlay('ov-planen'); toast('Für den Wochenplan vorgemerkt', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}
window.openPlanOverlay = openPlanOverlay;
window.confirmPlan = confirmPlan;

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
