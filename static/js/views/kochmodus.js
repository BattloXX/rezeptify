import { api } from '../api.js';
import { toast, x, scaleAmount } from '../utils.js';
import { S, showView } from '../app.js';

const KM = { recipe: null, steps: [], index: 0, timers: [], wakeLock: null, touchX: null };

export function initKochmodus() {
  window.kochNext = () => move(1);
  window.kochPrev = () => move(-1);
  window.exitKochmodus = exitKochmodus;
  window.startKochTimer = startTimer;
  window.toggleWakeLock = toggleWakeLock;
  const view = document.getElementById('view-kochmodus');
  if (!view || view.dataset.ready) return;
  view.dataset.ready = '1';
  view.addEventListener('touchstart', event => { KM.touchX = event.changedTouches[0].clientX; }, { passive: true });
  view.addEventListener('touchend', event => {
    if (KM.touchX === null) return;
    const diff = event.changedTouches[0].clientX - KM.touchX;
    KM.touchX = null;
    if (Math.abs(diff) > 55) move(diff < 0 ? 1 : -1);
  }, { passive: true });
}

export async function startKochmodus(id) {
  try {
    KM.recipe = S.current?.id === id ? S.current : await api('/api/rezepte/' + id);
    const data = await api('/api/rezepte/' + id + '/schritte');
    KM.steps = data.schritte || [];
    KM.index = 0;
    document.getElementById('ov-detail')?.classList.remove('on');
    document.body.style.overflow = 'hidden';
    showView('kochmodus');
    render();
    requestWakeLock();
  } catch (error) { toast('Kochmodus konnte nicht gestartet werden: ' + error.message, 'err'); }
}

function move(delta) {
  if (delta > 0 && KM.index >= KM.steps.length - 1) { exitKochmodus(); return; }
  const next = KM.index + delta;
  if (next < 0 || next >= KM.steps.length) return;
  KM.index = next;
  render();
}

function render() {
  const step = KM.steps[KM.index];
  const total = KM.steps.length;
  const title = KM.recipe?.titel || 'Kochmodus';
  document.getElementById('km-title').textContent = title;
  document.getElementById('km-progress-label').textContent = total ? `Schritt ${KM.index + 1} von ${total}` : 'Zubereitung';
  document.getElementById('km-progress-bar').style.width = total ? `${((KM.index + 1) / total) * 100}%` : '0%';
  document.getElementById('km-prev').disabled = KM.index === 0;
  document.getElementById('km-next').disabled = false;
  document.getElementById('km-next').innerHTML = KM.index >= total - 1
    ? '<span class="material-symbols-outlined">check</span>Fertig'
    : 'Weiter<span class="material-symbols-outlined">arrow_forward</span>';
  const ingredients = ingredientsForStep(step);
  document.getElementById('km-step').innerHTML = step
    ? `<p class="km-step-text">${x(step.text)}</p>
       ${ingredients ? `<div class="km-ingredients"><strong>Dafür bereitstellen</strong>${ingredients}</div>` : ''}
       ${step.timer_sekunden ? `<button class="km-timer-start" onclick="startKochTimer(${step.timer_sekunden}, ${KM.index})"><span class="material-symbols-outlined">timer</span>${duration(step.timer_sekunden)} starten</button>` : ''}`
    : `<p class="km-step-text">${x(KM.recipe?.zubereitung || 'Für dieses Rezept ist keine Zubereitung hinterlegt.')}</p>`;
  const wake = document.getElementById('km-wake');
  wake.hidden = !('wakeLock' in navigator);
  wake.classList.toggle('on', !!KM.wakeLock);
  wake.innerHTML = `<span class="material-symbols-outlined">${KM.wakeLock ? 'screen_lock_portrait' : 'screen_lock_rotation'}</span>${KM.wakeLock ? 'Display bleibt an' : 'Display anlassen'}`;
  renderTimers();
}

function ingredientsForStep(step) {
  if (!step?.zutaten_indices?.length || !KM.recipe?.zutaten) return '';
  return `<ul>${step.zutaten_indices.map(index => {
    const z = KM.recipe.zutaten[index];
    if (!z || z.gruppe) return '';
    return `<li>${x(scaleAmount(z.menge || '', 1))} ${x(z.einheit || '')} ${x(z.name || '')}</li>`;
  }).join('')}</ul>`;
}

function duration(seconds) {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes ? `${minutes} Min.${rest ? ` ${rest} Sek.` : ''}` : `${rest} Sek.`;
}

function startTimer(seconds, stepIndex) {
  const timer = { id: Date.now(), ends: Date.now() + seconds * 1000, stepIndex, done: false };
  KM.timers.push(timer);
  renderTimers();
  const interval = window.setInterval(() => {
    if (Date.now() < timer.ends) return renderTimers();
    timer.done = true;
    window.clearInterval(interval);
    renderTimers();
    toast('Timer fertig!', 'ok');
  }, 1000);
}

function renderTimers() {
  const tray = document.getElementById('km-timers');
  tray.innerHTML = KM.timers.map(timer => {
    const remaining = Math.max(0, Math.ceil((timer.ends - Date.now()) / 1000));
    return `<div class="km-timer ${timer.done ? 'done' : ''}"><span class="material-symbols-outlined">timer</span>Schritt ${timer.stepIndex + 1}: ${timer.done ? 'Fertig' : duration(remaining)}</div>`;
  }).join('');
}

async function requestWakeLock() {
  if (!('wakeLock' in navigator) || KM.wakeLock) return;
  try {
    KM.wakeLock = await navigator.wakeLock.request('screen');
    KM.wakeLock.addEventListener('release', () => { KM.wakeLock = null; render(); });
    render();
  } catch { /* Browser or system policy may deny the optional wake lock. */ }
}

async function toggleWakeLock() {
  if (KM.wakeLock) await KM.wakeLock.release();
  else await requestWakeLock();
}

async function exitKochmodus() {
  if (KM.wakeLock) await KM.wakeLock.release();
  document.body.style.overflow = '';
  if (window.location.pathname.startsWith('/rezept/')) history.pushState({}, document.title, '/');
  showView('home');
}
