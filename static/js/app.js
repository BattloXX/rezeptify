import { api, apiFetch, setAuth, clearAuth, hasAuth } from './api.js';
import { toast } from './utils.js';
import { initHome, loadGrid, loadKats, loadTags } from './views/home.js';
import { openDetail } from './views/detail.js';
import { openNewForm, openEditForm, setupTagInp, setupClipboardPaste } from './views/form.js';
import { initImport } from './views/import.js';
import { initBuch } from './views/buch.js';
import { initBot } from './views/bot.js';

// ── Global state (accessed by all views) ─────────────────────────────────────
export const S = {
  rezepte: [], total: 0,
  kategorien: [], tags: [],
  current: null, editId: null,
  importData: null, importFile: null,
  formTags: [], formNewImgs: [], formImgUrls: [],
  debT: null,
};

// ── Navigation ────────────────────────────────────────────────────────────────
export function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('on'));
  document.querySelectorAll('.bnav-item').forEach(b => b.classList.remove('on'));
  document.getElementById('view-' + name)?.classList.add('on');
  document.getElementById('nav-' + name)?.classList.add('on');
  if (name === 'buch') initBuch();
}
window.showView = showView;

// ── Login screen ──────────────────────────────────────────────────────────────
function showLogin(errMsg = '') {
  document.getElementById('app').style.display = 'none';
  const ls = document.getElementById('login-screen');
  ls.classList.add('on');
  document.getElementById('login-err').textContent = errMsg;
  document.getElementById('login-pwd').focus();
}

function hideLogin() {
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
    hideLogin();
    await initApp();
  } catch {
    clearAuth();
    document.getElementById('login-err').textContent = 'Falsches Passwort';
    btn.disabled = false;
  }
}
window.doLogin = doLogin;

// ── App init ──────────────────────────────────────────────────────────────────
async function initApp() {
  await Promise.all([loadKats(), loadTags()]);
  await loadGrid();
  setupTagInp();
  setupClipboardPaste();
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js').catch(() => {});
  }
  handleDeepLink();
}

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
  if (window.location.pathname === '/') {
    document.getElementById('ov-detail')?.classList.remove('on');
    document.body.style.overflow = '';
    S.current = null;
  } else {
    handleDeepLink();
  }
});

// ── Auth required event ───────────────────────────────────────────────────────
window.addEventListener('auth:required', () => showLogin('Sitzung abgelaufen'));

// ── Expose to global for inline onclick compatibility ─────────────────────────
window.openNewForm   = openNewForm;
window.openEditForm  = openEditForm;

// ── DOMContentLoaded ──────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('login-pwd')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') doLogin();
  });

  initHome();
  initImport();
  initBot();

  if (!hasAuth()) {
    // Try a test request — if 401 or no auth configured, show login
    api('/api/kategorien').then(() => {
      hideLogin();
      initApp();
    }).catch(() => {
      showLogin();
    });
  } else {
    // Already have stored credentials — validate them silently
    api('/api/kategorien').then(() => {
      hideLogin();
      initApp();
    }).catch(() => {
      showLogin('Bitte erneut anmelden');
    });
  }
});
