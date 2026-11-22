import { api, apiFetch, setAuth, clearAuth, hasAuth } from './api.js';
import { toast } from './utils.js';
import shoppingStore from './einkauf-store.js';
import { initHome, loadGrid, loadKats, loadTags } from './views/home.js';
import { openDetail } from './views/detail.js';
import { openNewForm, openEditForm, setupTagInp, setupClipboardPaste } from './views/form.js';
import { initImport } from './views/import.js';
import { initBuch } from './views/buch.js';
import { initBot } from './views/bot.js';
import { initKochmodus } from './views/kochmodus.js';
import { initEinkauf, loadEinkauf } from './views/einkauf.js';
import { initWochenplan, loadWochenplan } from './views/wochenplan.js';
import { initSystem, loadSystem } from './views/system.js';
import { initUpdateLog, loadUpdateLog } from './views/update-log.js';
import { initErrorLog, loadErrorLog } from './views/error-log.js';

// ── Global state (accessed by all views) ─────────────────────────────────────
export const S = {
  rezepte: [], total: 0,
  kategorien: [], tags: [],
  current: null, editId: null,
  importData: null, importFile: null,
  formTags: [], formNewImgs: [], formImgUrls: [], formNewImgUrls: [],
  debT: null,
};

let reloadStarted = false;
let serviceWorkerStarted = false;

function reloadForUpdate() {
  if (reloadStarted) return;
  reloadStarted = true;
  location.reload();
}

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator) || serviceWorkerStarted) return;
  serviceWorkerStarted = true;
  const hadController = !!navigator.serviceWorker.controller;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (hadController) reloadForUpdate();
  });
  try {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registrations.filter(reg => new URL(reg.scope).pathname.endsWith('/static/'))
      .map(reg => reg.unregister()));
    const reg = await navigator.serviceWorker.register('/service-worker', {
      scope: '/', updateViaCache: 'none',
    });
    await reg.update();
  } catch (_) {}
}

function watchAssetVersion() {
  const current = document.querySelector('meta[name="rezeptify-asset-version"]')?.content;
  if (!current) return;
  let lastCheck = null;
  const check = async () => {
    const now = Date.now();
    if (lastCheck !== null && now - lastCheck < 5 * 60 * 1000) return;
    lastCheck = now;
    try {
      const response = await fetch('/api/asset-version', { cache: 'no-store' });
      if (!response.ok) return;
      const { asset_version: target } = await response.json();
      if (typeof target !== 'string' || !target || target === current || reloadStarted) return;
      try {
        if (sessionStorage.getItem('rezeptify-asset-reload') === target) return;
        sessionStorage.setItem('rezeptify-asset-reload', target);
      } catch (_) {}
      reloadForUpdate();
    } catch (_) {}
  };
  check();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') check();
  });
}

// ── Navigation ────────────────────────────────────────────────────────────────
export function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('on'));
  document.querySelectorAll('.bnav-item').forEach(b => b.classList.remove('on'));
  document.getElementById('view-' + name)?.classList.add('on');
  document.getElementById('nav-' + name)?.classList.add('on');
  document.body.classList.toggle('kochmodus-active', name === 'kochmodus');
  if (name === 'buch') initBuch();
  if (name === 'einkauf') loadEinkauf();
  if (name === 'wochenplan') loadWochenplan();
  if (name === 'system') loadSystem();
  if (name === 'update-log') loadUpdateLog();
  if (name === 'error-log') loadErrorLog();
}
window.showView = showView;

// ── Login screen ──────────────────────────────────────────────────────────────
let authEnabled = null;

function showLogin(errMsg = '') {
  document.getElementById('startup-error').classList.remove('on');
  document.getElementById('app').style.display = 'none';
  const ls = document.getElementById('login-screen');
  ls.classList.add('on');
  document.getElementById('login-err').textContent = errMsg;
  document.getElementById('login-pwd').focus();
}

function hideLogin() {
  document.getElementById('startup-error').classList.remove('on');
  document.getElementById('login-screen').classList.remove('on');
  document.getElementById('app').style.display = '';
}

async function doLogin() {
  const pwd = document.getElementById('login-pwd').value;
  if (!pwd) return;
  const btn = document.getElementById('login-btn');
  btn.disabled = true;
  try {
    setAuth(pwd);
    await api('/api/kategorien');
    await initApp(!offlineStartup);
    offlineStartup = false;
    hideLogin();
    shoppingStore.sync();
  } catch (err) {
    clearAuth();
    showLogin(err.status === 401 ? 'Falsches Passwort' : 'Server nicht erreichbar: ' + err.message);
  } finally {
    btn.disabled = false;
  }
}
window.doLogin = doLogin;

// ── App init ──────────────────────────────────────────────────────────────────
async function initApp(followDeepLink = true) {
  let loadError = null;
  const captureError = event => {
    if (event.detail.requestPath !== '/api/einkauf/sync') loadError ||= event.detail;
  };
  window.addEventListener('api:error', captureError);
  try {
    await Promise.all([loadKats(), loadTags()]);
    if (loadError) throw loadError;
    await loadGrid();
    if (loadError) throw loadError;
  } finally {
    window.removeEventListener('api:error', captureError);
  }
  setupTagInp();
  setupClipboardPaste();
  registerServiceWorker();
  if (followDeepLink) handleDeepLink();
}

function showStartupError(err) {
  document.getElementById('app').style.display = 'none';
  document.getElementById('login-screen').classList.remove('on');
  document.getElementById('startup-error-message').textContent = err.message;
  document.getElementById('startup-error').classList.add('on');
}

let offlineStartup = false;
let startupRunning = false;

async function startup() {
  if (startupRunning) return;
  startupRunning = true;
  const btn = document.getElementById('startup-retry-btn');
  btn.disabled = true;
  const hadAuth = hasAuth();
  let configLoaded = false;
  try {
    await shoppingStore.init();
    if (navigator.onLine === false) throw new TypeError('Offline');
    const response = await fetch('/api/config');
    if (response.status === 404) {
      authEnabled = null;
    } else {
      if (!response.ok) throw new Error(`Server nicht erreichbar (HTTP ${response.status})`);
      const config = await response.json();
      if (typeof config?.auth_enabled !== 'boolean') throw new Error('Ungültige Serverkonfiguration');
      authEnabled = config.auth_enabled;
    }
    configLoaded = true;
    if (authEnabled === false) clearAuth();
    else await api('/api/kategorien');
    await initApp(!offlineStartup);
    offlineStartup = false;
    hideLogin();
    shoppingStore.sync();
  } catch (err) {
    if (navigator.onLine === false || (!configLoaded && err instanceof TypeError)) {
      const firstOfflineStart = !offlineStartup;
      offlineStartup = true;
      hideLogin();
      if (firstOfflineStart) showView('einkauf');
      registerServiceWorker();
      toast('Offline – Einkaufsliste verfügbar');
    } else if (configLoaded && authEnabled !== false && err.status === 401) {
      showLogin(hadAuth ? 'Bitte erneut anmelden' : '');
    } else {
      showStartupError(err);
    }
  } finally {
    startupRunning = false;
    btn.disabled = false;
  }
}

window.addEventListener('online', () => { if (offlineStartup) startup(); });

function handleDeepLink() {
  const m = window.location.pathname.match(/^\/rezept\/([^/]+)$/);
  if (!m) return;
  fetch('/api/rezepte/slug/' + encodeURIComponent(m[1]),
    { headers: localStorage.getItem('rzpf-auth') ? { 'Authorization': 'Basic ' + localStorage.getItem('rzpf-auth') } : {} }
  )
    .then(r => r.ok ? r.json() : null)
    .then(r => { if (r) openDetail(r.id); })
    .catch(() => {});
}

// ── PWA Install ───────────────────────────────────────────────────────────────
let deferredPrompt = null;

function isPWADismissed() { return localStorage.getItem('pwa-dismissed') === '1'; }
function isStandalone()   { return window.matchMedia('(display-mode: standalone)').matches || navigator.standalone; }

window.dismissPWA = () => {
  localStorage.setItem('pwa-dismissed', '1');
  document.getElementById('pwa-banner')?.classList.remove('show');
  document.getElementById('ios-hint')?.classList.remove('show');
};

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  if (!isStandalone() && !isPWADismissed()) {
    document.getElementById('pwa-banner')?.classList.add('show');
  }
});

async function triggerInstall() {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  await deferredPrompt.userChoice;
  deferredPrompt = null;
  window.dismissPWA();
}
document.getElementById('pwa-install-btn')?.addEventListener('click', triggerInstall);
document.getElementById('pwa-install-btn2')?.addEventListener('click', triggerInstall);

window.addEventListener('load', () => {
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;
  if (isIOS && !isStandalone() && !isPWADismissed()) {
    setTimeout(() => {
      const banner = document.getElementById('pwa-banner');
      const btn    = document.getElementById('pwa-install-btn');
      if (!banner || !btn) return;
      banner.classList.add('show');
      btn.textContent = 'Wie?';
      btn.onclick = () => {
        const hint = document.getElementById('ios-hint');
        hint?.classList.toggle('show');
        setTimeout(() => hint?.classList.remove('show'), 6000);
      };
    }, 2000);
  }
});

window.addEventListener('appinstalled', () => {
  window.dismissPWA();
  toast('App installiert ✓', 'ok');
});

// ── Back/forward navigation ───────────────────────────────────────────────────
window.addEventListener('popstate', () => {
  if (window.location.pathname === '/update-log') {
    showView('update-log');
  } else if (window.location.pathname === '/error-log') {
    showView('error-log');
  } else if (window.location.pathname === '/') {
    document.getElementById('ov-detail')?.classList.remove('on');
    document.body.style.overflow = '';
    S.current = null;
  } else {
    handleDeepLink();
  }
});

// ── Auth required event ───────────────────────────────────────────────────────
window.addEventListener('auth:required', () => {
  if (authEnabled === false) toast('Nicht autorisiert', 'err');
  else showLogin('Sitzung abgelaufen');
});

// ── Expose to global for inline onclick compatibility ─────────────────────────
window.openNewForm   = openNewForm;
window.openEditForm  = openEditForm;

// ── DOMContentLoaded ──────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  watchAssetVersion();
  document.getElementById('startup-retry-btn').addEventListener('click', startup);
  document.getElementById('login-pwd')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') doLogin();
  });

  initHome();
  initImport();
  initBot();
  initKochmodus();
  initEinkauf();
  shoppingStore.init();
  initWochenplan();
  initSystem();
  initUpdateLog();
  initErrorLog();

  if (window.location.pathname === '/update-log' || window.location.pathname === '/error-log') {
    registerServiceWorker();
    hideLogin();
    showView(window.location.pathname === '/error-log' ? 'error-log' : 'update-log');
    return;
  }

  startup();
});
