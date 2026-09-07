import { api } from '../api.js';
import { toast, x, EM, optimisticToggle, renderCardStars } from '../utils.js';
import { S } from '../app.js';
import { openDetail } from './detail.js';

let currentSort = 'neu';

export function initHome() {
  // exposes needed for inline handlers
  window.debounce      = debounce;
  window.toggleFilters = toggleFilters;
  window.setSort       = setSort;
  window.loadGrid      = loadGrid;
  window.filterByTag   = filterByTag;
  window.openQuickSuggestion = openQuickSuggestion;
}

function openQuickSuggestion(filters) {
  window.showView?.('bot');
  window.openVorschlag?.(filters);
}

export async function loadKats() {
  S.kategorien = await api('/api/kategorien').catch(() => []);
  const opts = S.kategorien.map(k => `<option value="${x(k)}">${x(k)}</option>`).join('');
  document.getElementById('f-kat').innerHTML      = `<option value="">Alle</option>${opts}`;
  document.getElementById('f-kat-form').innerHTML = `<option value="">– Keine –</option>${opts}`;
}

export async function loadTags() {
  S.tags = await api('/api/tags').catch(() => []);
  document.getElementById('f-tag').innerHTML =
    `<option value="">Alle Tags</option>` + S.tags.map(t => `<option>${x(t)}</option>`).join('');
}

export function setSort(s) {
  currentSort = s;
  document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('on'));
  document.getElementById('sort-' + s)?.classList.add('on');
  loadGrid();
}

export async function loadGrid() {
  showSkeletons();
  const q = new URLSearchParams();
  const s = document.getElementById('search')?.value.trim();
  const k = document.getElementById('f-kat')?.value;
  const d = document.getElementById('f-diff')?.value;
  const t = document.getElementById('f-tag')?.value;
  if (s) q.set('suche', s);
  if (k) q.set('kategorie', k);
  if (d) q.set('schwierigkeit', d);
  if (t) q.set('tag', t);
  q.set('sort', currentSort);
  try {
    const data = await api('/api/rezepte?' + q);
    S.rezepte = data.items;
    S.total   = data.total;
    renderGrid();
    loadHistorySections();
    const tc = document.getElementById('topbar-count');
    if (tc) tc.textContent = S.total + ' Rezepte';
  } catch(e) {
    toast('Ladefehler: ' + e.message, 'err');
  }
}

function debounce() {
  clearTimeout(S.debT);
  S.debT = setTimeout(loadGrid, 300);
}

function toggleFilters() {
  document.getElementById('filters')?.classList.toggle('on');
  document.getElementById('filter-toggle')?.classList.toggle('on');
}

function showSkeletons() {
  const g = document.getElementById('grid');
  if (!g) return;
  g.innerHTML = Array(6).fill(0).map(() => `
    <article class="card skeleton">
      <div class="card-thumb skeleton-box"></div>
      <div class="card-body">
        <div class="skel-line w-40" style="height:10px;margin-bottom:8px"></div>
        <div class="skel-line w-80" style="height:16px;margin-bottom:8px"></div>
        <div class="skel-line w-60" style="height:11px"></div>
      </div>
    </article>`).join('');
}

function renderGrid() {
  const g = document.getElementById('grid');
  if (!g) return;
  const cl = document.getElementById('count-line');
  if (cl) cl.textContent = S.total + (S.total === 1 ? ' Rezept gefunden' : ' Rezepte gefunden');
  if (!S.rezepte.length) {
    g.innerHTML = `<div class="empty">
      <div class="empty-icon">🔍</div>
      <h3>Keine Rezepte gefunden</h3>
      <p>Andere Suchbegriffe oder Filter versuchen</p>
    </div>`;
    return;
  }
  g.innerHTML = renderRecipeCards(S.rezepte);
}

function renderRecipeCards(recipes, compact = false) {
  return recipes.map(r => {
    const em       = EM[r.kategorie] || '🍴';
    const img      = r.haupt_bild || r.bilder?.[0]?.url;
    const thumb    = img
      ? `<img src="${x(img)}" alt="" loading="lazy" onerror="this.style.display='none'">`
      : `<span class="card-thumb-emoji">${em}</span>`;
    const imgCount = r.bilder?.length || 0;
    const gz       = (r.zeit_vorb||0) + (r.zeit_koch||0);
    const badge    = r.quelle_typ && r.quelle_typ !== 'manuell'
      ? `<span class="card-badge">${x(r.quelle_typ)}</span>` : '';
    const countBadge = imgCount > 1
      ? `<span class="card-img-count"><span class="material-symbols-outlined">photo_library</span>${imgCount}</span>` : '';
    const kcalHtml = r.kalorien_pro_portion
      ? `<span class="card-meta-i card-kcal">${r.kalorien_pro_portion} <span style="font-weight:400;font-size:0.9em">kcal</span></span>` : '';
    return `<article class="card${compact ? ' history-card' : ''}" data-id="${r.id}" onclick="openDetail(${r.id})">
      <div class="card-thumb">${thumb}${badge}${countBadge}
        <button class="card-favorite${r.favorit ? ' on' : ''}" aria-label="${r.favorit ? 'Favorit entfernen' : 'Als Favorit markieren'}" onclick="toggleFavorite(event,${r.id})">${r.favorit ? '♥' : '♡'}</button>
        <div class="card-hover-overlay">
          <span class="card-hover-label">Öffnen</span>
          <span class="material-symbols-outlined card-hover-arrow">arrow_forward</span>
        </div>
      </div>
      <div class="card-body">
        <div class="card-cat">${x(r.kategorie || 'Sonstiges')}</div>
        <div class="card-title">${x(r.titel)}</div>
        <div class="card-meta">
          ${gz ? `<span class="card-meta-i"><span class="material-symbols-outlined">schedule</span>${gz} min</span>` : ''}
          ${r.portionen ? `<span class="card-meta-i"><span class="material-symbols-outlined">group</span>${r.portionen}</span>` : ''}
          ${kcalHtml}
        </div>
        ${r.schwierigkeit ? `<span class="diff-tag ${x(r.schwierigkeit)}">${x(r.schwierigkeit)}</span>` : ''}
        ${renderCardStars(r.bewertung)}
      </div>
    </article>`;
  }).join('');
}

async function loadHistorySections() {
  const container = document.getElementById('home-history-sections');
  if (!container) return;
  const sections = [
    ['Favoriten', 'sort=favoriten&nur_favoriten=true'],
    ['Zuletzt gekocht', 'sort=zuletzt_gekocht&nur_gekocht=true'],
    ['Häufig gekocht', 'sort=haeufig_gekocht&nur_gekocht=true'],
    ['Lange nicht gekocht', 'sort=lange_nicht_gekocht'],
  ];
  const results = await Promise.all(sections.map(async ([title, query]) => {
    try {
      const data = await api('/api/rezepte?' + query + '&limit=10');
      return { title, items: data.items };
    } catch { return { title, items: [] }; }
  }));
  container.innerHTML = results.filter(section => section.items.length).map(section => `
    <section class="home-history-section">
      <h2>${section.title}</h2>
      <div class="home-history-row">${renderRecipeCards(section.items, true)}</div>
    </section>`).join('');
}

async function toggleFavorite(event, rid) {
  event.stopPropagation();
  const recipe = (S.rezepte || []).find(r => r.id === rid)
    || (S.current?.id === rid ? S.current : { id: rid, favorit: event.currentTarget.classList.contains('on') });
  const old = Boolean(recipe.favorit);
  const update = (value) => {
    recipe.favorit = value;
    const listRecipe = S.rezepte?.find(r => r.id === rid);
    if (listRecipe) listRecipe.favorit = value;
    if (S.current?.id === rid) S.current.favorit = value;
    document.querySelectorAll(`.card[data-id="${rid}"] .card-favorite`).forEach(button => {
      button.classList.toggle('on', value);
      button.textContent = value ? '♥' : '♡';
      button.setAttribute('aria-label', value ? 'Favorit entfernen' : 'Als Favorit markieren');
    });
  };
  try {
    await optimisticToggle({
      apply: () => update(!old),
      request: () => api('/api/rezepte/' + rid + '/favorit', { method: 'PATCH', body: JSON.stringify({ favorit: !old }) }),
      revert: () => update(old),
    });
  } catch (_) { /* The helper already restored state and showed a toast. */ }
}
window.toggleFavorite = toggleFavorite;

function filterByTag(tag) {
  const el = document.getElementById('ov-detail');
  if (el) {
    el.classList.remove('on');
    document.body.style.overflow = '';
    S.current = null;
    if (window.location.pathname.startsWith('/rezept/')) {
      history.pushState({}, document.title, '/');
    }
  }
  const tf = document.getElementById('f-tag');
  if (tf) tf.value = tag;
  document.getElementById('filters')?.classList.add('on');
  document.getElementById('filter-toggle')?.classList.add('on');
  showView('home');
  loadGrid();
}
window.filterByTag = filterByTag;
