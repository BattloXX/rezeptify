// ── HTML escape ───────────────────────────────────────────────────────────────
export function x(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Toast ─────────────────────────────────────────────────────────────────────
let _toastTimer;
export function toast(msg, type = '') {
  const el = document.getElementById('toast');
  clearTimeout(_toastTimer);
  el.textContent = msg;
  el.className = 'toast on' + (type ? ' ' + type : '');
  _toastTimer = setTimeout(() => el.classList.remove('on'), 3500);
}

// ── Number formatting for ingredient scaling ─────────────────────────────────
export function formatNum(n) {
  if (n === 0) return '0';
  const fracs = [[0.25,'¼'],[0.5,'½'],[0.75,'¾'],[0.33,'⅓'],[0.67,'⅔']];
  const whole = Math.floor(n);
  const dec   = n - whole;
  for (const [v, sym] of fracs) {
    if (Math.abs(dec - v) < 0.06) return whole > 0 ? whole + sym : sym;
  }
  if (n >= 100) return Math.round(n).toString();
  if (n >= 10)  return (Math.round(n * 2) / 2).toString();
  if (n >= 1)   return (Math.round(n * 4) / 4).toString();
  return (Math.round(n * 10) / 10).toString();
}

export function scaleAmount(menge, factor) {
  if (!menge || menge.trim() === '') return '';
  const frac  = menge.trim().match(/^(\d+)\/(\d+)$/);
  if (frac)  return formatNum((parseInt(frac[1]) / parseInt(frac[2])) * factor);
  const mix   = menge.trim().match(/^(\d+)\s+(\d+)\/(\d+)$/);
  if (mix)   return formatNum((parseInt(mix[1]) + parseInt(mix[2])/parseInt(mix[3])) * factor);
  const range = menge.trim().match(/^(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)$/);
  if (range) return formatNum(parseFloat(range[1].replace(',','.')) * factor) + '–' + formatNum(parseFloat(range[2].replace(',','.')) * factor);
  const num = parseFloat(menge.replace(',','.'));
  if (!isNaN(num)) return formatNum(num * factor);
  return x(menge);
}

// ── Category emoji map ────────────────────────────────────────────────────────
export const EM = {
  'Frühstück':'🌅','Vorspeise':'🥗','Hauptgericht':'🍽️','Dessert':'🍰',
  'Snack':'🥨','Getränk':'🥤','Backen':'🥐','Salat':'🥙','Suppe':'🍜','Sonstiges':'🍴'
};

// ── Star rendering ────────────────────────────────────────────────────────────
export const STAR_LABELS = ['','Nicht so gut','Geht so','Gut','Sehr gut','Ausgezeichnet'];
export function starLabel(n) { return STAR_LABELS[n] || ''; }

export function renderCardStars(bewertung) {
  if (!bewertung) return '';
  return '<div class="card-stars">' +
    [1,2,3,4,5].map(i =>
      `<span class="card-star ${i <= bewertung ? 'filled' : 'empty'}">${i <= bewertung ? '★' : '☆'}</span>`
    ).join('') + '</div>';
}

export function renderDetailStars(bewertung, rid) {
  return [1,2,3,4,5].map(i =>
    `<span class="star ${bewertung && i <= bewertung ? 'filled' : 'empty'}"
      onclick="setBewertung(${rid},${i})"
      onmouseenter="previewStars(${i})"
      onmouseleave="resetStarPreview(${rid},${bewertung||0})"
    >${bewertung && i <= bewertung ? '★' : '☆'}</span>`
  ).join('');
}
