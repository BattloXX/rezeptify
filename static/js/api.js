// ── Auth token storage ────────────────────────────────────────────────────────
let _authHeader = localStorage.getItem('rzpf-auth') || '';

export function setAuth(password) {
  _authHeader = btoa(':' + password);
  localStorage.setItem('rzpf-auth', _authHeader);
}

export function clearAuth() {
  _authHeader = '';
  localStorage.removeItem('rzpf-auth');
}

export function hasAuth() {
  return !!_authHeader;
}

// ── Core fetch wrapper ────────────────────────────────────────────────────────
export async function api(path, opts = {}) {
  const isForm = opts.body instanceof FormData;
  const headers = {
    ...(isForm ? {} : { 'Content-Type': 'application/json' }),
    ...(_authHeader ? { 'Authorization': 'Basic ' + _authHeader } : {}),
    ...(opts.headers || {}),
  };
  const r = await fetch(path, { ...opts, headers });
  if (r.status === 401) {
    clearAuth();
    window.dispatchEvent(new CustomEvent('auth:required'));
    throw new Error('Nicht autorisiert');
  }
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(e.detail || r.statusText);
  }
  return r.json();
}

// ── Raw fetch with auth (for FormData endpoints) ──────────────────────────────
export async function apiFetch(path, opts = {}) {
  const headers = {
    ...(_authHeader ? { 'Authorization': 'Basic ' + _authHeader } : {}),
    ...(opts.headers || {}),
  };
  const r = await fetch(path, { ...opts, headers });
  if (r.status === 401) {
    clearAuth();
    window.dispatchEvent(new CustomEvent('auth:required'));
    throw new Error('Nicht autorisiert');
  }
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(e.detail || r.statusText);
  }
  return r.json();
}
