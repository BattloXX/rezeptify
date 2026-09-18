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

function validationMessage(detail) {
  if (typeof detail === 'string' && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const messages = detail.map(item => {
      if (typeof item === 'string') return item;
      if (!item || typeof item !== 'object') return '';
      const field = Array.isArray(item.loc) ? item.loc.filter(part => part !== 'body').join('.') : '';
      const message = typeof item.msg === 'string' ? item.msg : '';
      return field && message ? `${field}: ${message}` : message;
    }).filter(Boolean);
    if (messages.length) return messages.join('; ');
  }
  return '';
}

async function responseError(response) {
  // A reverse proxy may reject a multipart upload before FastAPI can produce
  // its JSON {detail: ...} response. Under HTTP/2 statusText is often empty,
  // so it must never be the only fallback shown to the user.
  const body = await response.text().catch(() => '');
  if (body) {
    try {
      const payload = JSON.parse(body);
      const message = validationMessage(payload.detail)
        || validationMessage(payload.message)
        || validationMessage(payload.error);
      if (message) return message;
    } catch (_) {
      const text = body.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
      if (text) return text;
    }
  }
  if (response.status === 413) {
    return 'Datei zu groß oder vom Webserver abgelehnt (HTTP 413)';
  }
  return response.statusText || `Anfrage fehlgeschlagen (HTTP ${response.status})`;
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
    throw new Error(await responseError(r));
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
    throw new Error(await responseError(r));
  }
  return r.json();
}
