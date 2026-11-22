import { createClock, makeOp, applyOpLocal, rebase, sortedEntries, normalizeName, unitFamily, rangNach, rangZwischen } from './einkauf-core.js';

const notify = msg => { if (typeof document !== 'undefined') import('./utils.js').then(({ toast }) => toast(msg)); };

// A snapshot is committed in one transaction: seq must never advance without its entries/outbox.
export function createStorage(warn = notify) {
  let db, memory = null, warned = false;
  function fallback() {
    db = null;
    if (!warned) { warned = true; warn('Offline-Speicher nicht verfügbar'); }
  }
  function transaction(mode, fn) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['eintraege', 'outbox', 'meta'], mode);
      const result = fn(tx);
      tx.oncomplete = () => resolve(result);
      tx.onerror = tx.onabort = () => reject(tx.error || new Error('IndexedDB'));
    });
  }
  return {
    async load() {
      try {
        db = await new Promise((resolve, reject) => {
          const request = indexedDB.open('rezeptify-einkauf', 1);
          request.onupgradeneeded = () => {
            request.result.createObjectStore('eintraege', { keyPath: 'uuid' });
            request.result.createObjectStore('outbox', { keyPath: 'op_id' });
            request.result.createObjectStore('meta', { keyPath: 'key' });
          };
          request.onsuccess = () => resolve(request.result);
          request.onerror = request.onblocked = () => reject(request.error);
        });
        const result = {};
        await transaction('readonly', tx => {
          for (const name of ['eintraege', 'outbox', 'meta']) {
            tx.objectStore(name).getAll().onsuccess = e => { result[name] = e.target.result; };
          }
        });
        memory = { entries: result.eintraege, ops: result.outbox.sort((a, b) => a.nr - b.nr),
          ...Object.fromEntries(result.meta.map(row => [row.key, row.value])) };
      } catch { fallback(); }
      return memory;
    },
    async save(snapshot) {
      memory = structuredClone(snapshot);
      if (!db) return;
      try {
        await transaction('readwrite', tx => {
          for (const [name, rows] of [['eintraege', snapshot.entries], ['outbox', snapshot.ops],
            ['meta', Object.entries(snapshot).filter(([key]) => key !== 'entries' && key !== 'ops').map(([key, value]) => ({ key, value }))]]) {
            const target = tx.objectStore(name);
            target.clear();
            for (const row of rows) target.put(row);
          }
        });
      } catch { fallback(); }
    },
  };
}

export function createStore({ api = (path, opts) => import('./api.js').then(m => m.api(path, opts)),
  storage = createStorage(), now = Date.now, toast = notify } = {}) {
  const events = new EventTarget();
  let initialized = false, initializing, server = new Map(), state = new Map(), aliases = new Map(), ops = [];
  let kategorien = [], laeden = [], reihenfolgen = {}, ladenId = null, pendingLaden = null, catalogLoaded = false, catalogAt = 0;
  let clock, geraet, liste = null, seq = 0, nr = 0, lastSync = null, fehler = null;
  let timer, running, retry = 0, batchSize = 200, writes = Promise.resolve(), disposed = false;
  const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
  const visible = () => typeof document === 'undefined' || document.visibilityState === 'visible';
  function emit(type) { events.dispatchEvent(new Event(type)); }
  function persist() {
    const snapshot = { entries: [...server.values()], ops: structuredClone(ops), aliases: [...aliases],
      seq, clock: clock.state(), geraet, liste, nr, lastSync, kategorien, laeden, reihenfolgen, ladenId, pendingLaden };
    writes = writes.then(() => storage.save(snapshot)).catch(() => toast('Offline-Speicher nicht verfügbar'));
    return writes;
  }
  function rebuild() {
    const result = rebase(server, aliases, ops.map(({ nr: order, ...op }) => op));
    state = result.state;
    ops = result.pendingOps.map((op, i) => ({ ...op, nr: ops[i].nr }));
    emit('change'); emit('status');
  }
  function pollDelay() {
    return typeof document !== 'undefined' && document.getElementById('view-einkauf')?.classList.contains('on') ? 3000 : 30000;
  }
  function scheduleSync(delay = 300) {
    clearTimeout(timer);
    if (disposed || !initialized || !visible() || !online()) return;
    timer = setTimeout(() => { sync(); }, delay);
    timer.unref?.();
  }
  function enqueue(typ, id, data) {
    if (!initialized) throw new Error('Einkaufsliste wird geladen');
    const op = makeOp(clock, typ, id, data);
    const result = applyOpLocal(state, op);
    if (result.abgelehnt) throw new Error(result.abgelehnt);
    ops.push({ ...op, nr: ++nr });
    persist(); emit('change'); emit('status'); scheduleSync(300);
    return result.ziel;
  }
  function rejectBatch(batch) {
    for (const op of batch) toast(`Änderung an ${state.get(op.eintrag)?.name || op.daten.name || 'Einkaufsliste'} wurde verworfen`);
    const ids = new Set(batch.map(op => op.op_id));
    ops = ops.filter(op => !ids.has(op.op_id));
  }
  async function refreshCatalog() {
    if (!online()) return;
    const [cats, shops] = await Promise.all([api('/api/einkauf/kategorien'), api('/api/einkauf/laeden')]);
    const orders = await Promise.all(shops.laeden.map(async shop => {
      const result = await api(`/api/einkauf/kategorien?laden=${shop.id}`);
      return [shop.id, result.kategorien];
    }));
    kategorien = cats.kategorien; laeden = shops.laeden; reihenfolgen = Object.fromEntries(orders);
    catalogLoaded = true; catalogAt = now();
    emit('change'); await persist();
  }
  async function flushLaden() {
    if (!pendingLaden || !liste) return;
    const pending = pendingLaden;
    await writes;
    try {
      await api(`/api/einkauf/listen/${liste}`, { method: 'PATCH', body: JSON.stringify({ laden_id: pending.value }) });
    } catch (error) {
      if (error.status !== 404) throw error;
      toast('Laden nicht mehr vorhanden');
      if (pendingLaden === pending) ladenId = null;
    }
    if (pendingLaden === pending) pendingLaden = null;
    await persist();
  }
  async function run() {
    clearTimeout(timer);
    if (!initialized || !online()) { emit('status'); return; }
    let delay = pollDelay();
    try {
      if (pendingLaden && liste) await flushLaden();
      do {
        const batch = ops.slice(0, batchSize);
        let answer;
        try {
          const current = clock.state();
          const hlc = `${String(current.ms).padStart(13, '0')}-${current.counter.toString(16).padStart(4, '0')}-${geraet}`;
          answer = await api('/api/einkauf/sync', { method: 'POST', body: JSON.stringify({
            liste, seit: seq, hlc, ops: batch.map(({ nr: order, ...op }) => op),
          }) });
        } catch (error) {
          if (error.status === 413 && batch.length > 1) { batchSize = Math.max(1, Math.floor(batch.length / 2)); continue; }
          if (error.status >= 400 && error.status < 500 && error.status !== 401 && error.status !== 413) {
            rejectBatch(batch); rebuild(); await persist();
            if (ops.length) continue;
          }
          throw error;
        }
        for (const row of answer.eintraege || []) {
          if (row.geloescht && Number(row.hlc_geloescht.slice(0, 13)) < now() - 30 * 86400000) server.delete(row.uuid);
          else server.set(row.uuid, row);
        }
        for (const [id, row] of server) if (row.geloescht && Number(row.hlc_geloescht.slice(0, 13)) < now() - 30 * 86400000) server.delete(id);
        for (const alias of answer.aliase || []) aliases.set(alias.alt, alias.ziel);
        const results = answer.ergebnisse || [];
        rejectBatch(batch.filter(op => results.some(r => r.op_id === op.op_id && r.ergebnis === 'abgelehnt')));
        const confirmed = new Set(results.map(r => r.op_id));
        ops = ops.filter(op => !confirmed.has(op.op_id));
        seq = answer.seq; liste = answer.liste; clock.observe(answer.hlc);
        if (!pendingLaden && answer.listen) ladenId = answer.listen.find(row => row.uuid === liste)?.laden_id ?? null;
        await flushLaden();
        lastSync = now(); fehler = null; retry = 0;
        rebuild(); await persist();
        // A malformed response must not cause an endless immediate retry.
        if (batch.length && !batch.some(op => confirmed.has(op.op_id))) break;
      } while (ops.length && online());
      if (!catalogLoaded || now() - catalogAt > 30000) await refreshCatalog();
    } catch (error) {
      fehler = error.message;
      delay = Math.min(60000, 2000 * 2 ** Math.min(retry++, 5));
      emit('status');
    } finally { scheduleSync(delay); }
  }
  function sync() {
    if (running) return running;
    running = run().finally(() => { running = null; });
    return running;
  }
  const wake = () => { emit('status'); if (visible()) sync(); else clearTimeout(timer); };
  const connection = () => { emit('status'); if (online()) wake(); else clearTimeout(timer); };
  const store = {
    addEventListener: (...args) => events.addEventListener(...args),
    removeEventListener: (...args) => events.removeEventListener(...args),
    init() {
      if (initializing) return initializing;
      initializing = (async () => {
        const saved = await storage.load();
        geraet = saved?.geraet || crypto.randomUUID().replace(/-/g, '').slice(0, 20);
        clock = createClock(geraet, now, saved?.clock);
        server = new Map((saved?.entries || []).map(row => [row.uuid, row]));
        aliases = new Map(saved?.aliases || []); ops = saved?.ops || [];
        seq = saved?.seq || 0; liste = saved?.liste || null; nr = saved?.nr || 0; lastSync = saved?.lastSync || null;
        kategorien = saved?.kategorien || []; laeden = saved?.laeden || []; reihenfolgen = saved?.reihenfolgen || {};
        ladenId = saved?.ladenId ?? null; pendingLaden = saved?.pendingLaden || null;
        initialized = true; rebuild(); await persist();
        if (online()) { try { await refreshCatalog(); } catch { /* Keep the cached catalog offline. */ } }
        globalThis.window?.addEventListener('online', connection);
        globalThis.window?.addEventListener('offline', connection);
        globalThis.window?.addEventListener('focus', wake);
        globalThis.document?.addEventListener('visibilitychange', wake);
        scheduleSync(0);
        return store;
      })();
      return initializing;
    },
    entries: () => sortedEntries(state),
    kategorien: () => structuredClone(reihenfolgen[ladenId] || kategorien),
    laeden: () => structuredClone(laeden),
    ladenId: () => ladenId,
    setLaden(id) {
      ladenId = id; pendingLaden = { value: id };
      persist(); emit('change'); emit('status'); scheduleSync(0);
    },
    async saveLaden(id, values) {
      await api('/api/einkauf/laeden' + (id == null ? '' : `/${id}`), {
        method: id == null ? 'POST' : 'PATCH', body: JSON.stringify(values),
      });
      await refreshCatalog();
    },
    async deleteLaden(id) {
      await api(`/api/einkauf/laeden/${id}`, { method: 'DELETE' });
      if (ladenId === id) { ladenId = null; pendingLaden = null; }
      await refreshCatalog();
    },
    async saveReihenfolge(id, ids) {
      await api(`/api/einkauf/laeden/${id}/reihenfolge`, { method: 'PUT', body: JSON.stringify({ kategorien: ids }) });
      await refreshCatalog();
    },
    kategorienFuer: id => structuredClone(reihenfolgen[id] || kategorien),
    setKategorie: (id, kategorie_id) => enqueue('inhalt_setzen', id, { kategorie_id }),
    status: () => ({ online: online(), pending: ops.length + (pendingLaden ? 1 : 0), lastSync, fehler }),
    isInitialized: () => initialized,
    sync, scheduleSync,
    add(name, { menge = null, einheit = null, menge_text = null, notiz = null, herkunft = [], manuell = true } = {}) {
      const existing = !menge_text && store.entries().find(row => !row.erledigt && !row.menge_text &&
        normalizeName(row.name) === normalizeName(name) && unitFamily(row.einheit) === unitFamily(einheit));
      if (existing) return enqueue('menge_plus', existing.uuid, { menge: menge ?? (unitFamily(einheit) === '' ? 1 : 0), einheit });
      return enqueue('anlegen', crypto.randomUUID(), { name, menge, einheit, menge_text, notiz, herkunft, manuell,
        rang: rangNach([...state.values()].map(row => row.rang).sort().at(-1) ?? null) });
    },
    restore(entry) {
      const id = enqueue('anlegen', crypto.randomUUID(), {
        name: entry.name, menge: entry.menge, einheit: entry.einheit, menge_text: entry.menge_text,
        notiz: entry.notiz, herkunft: entry.herkunft || [], manuell: entry.manuell,
        rang: entry.rang, kategorie_id: entry.kategorie_id ?? null,
      });
      if (entry.erledigt) store.setDone(id, true);
      return id;
    },
    toggle(id) { return store.setDone(id, !state.get(id)?.erledigt); },
    setDone: (id, erledigt) => enqueue('status_setzen', id, { erledigt }),
    setAmount: (id, menge, einheit, menge_text) => enqueue('menge_setzen', id, { menge, einheit, menge_text }),
    plus: (id, delta) => enqueue('menge_plus', id, { menge: delta, einheit: state.get(id)?.einheit ?? null }),
    rename: (id, name) => enqueue('inhalt_setzen', id, { name }),
    setNote: (id, notiz) => enqueue('inhalt_setzen', id, { notiz }),
    removeRecipe(rezeptId) {
      for (const row of store.entries()) if ((row.herkunft || []).some(origin => origin.rezept_id === rezeptId))
        enqueue('herkunft_entfernen', row.uuid, { rezept_id: rezeptId });
    },
    remove: id => enqueue('loeschen', id, {}),
    move: (id, vorUuid, nachUuid) => enqueue('verschieben', id, { rang: rangZwischen(state.get(vorUuid)?.rang ?? null, state.get(nachUuid)?.rang ?? null) }),
    clearDone() {
      const done = store.entries().filter(row => row.erledigt);
      for (let i = 0; i < done.length; i += 500) enqueue('erledigte_loeschen', null, {
        eintraege: done.slice(i, i + 500).map(({ uuid, hlc_status }) => ({ uuid, hlc_status })),
      });
    },
    dispose() {
      disposed = true; clearTimeout(timer);
      globalThis.window?.removeEventListener('online', connection);
      globalThis.window?.removeEventListener('offline', connection);
      globalThis.window?.removeEventListener('focus', wake);
      globalThis.document?.removeEventListener('visibilitychange', wake);
      return writes;
    },
  };
  return store;
}

const store = createStore();
export default store;
export function onAnyShoppingChange() { if (store.isInitialized()) return store.sync(); }
