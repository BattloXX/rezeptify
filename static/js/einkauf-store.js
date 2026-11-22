import { createClock, makeOp, applyOpLocal, rebase, sortedEntries, normalizeName, unitFamily, rangNach, rangZwischen } from './einkauf-core.js';

const notify = msg => { if (typeof document !== 'undefined') import('./utils.js').then(({ toast }) => toast(msg)); };

// Pure migration also used when IndexedDB is unavailable. Null denotes an undiscovered default list.
export function migrateV1(snapshot) {
  if (!snapshot || snapshot.version === 2) return snapshot;
  const liste = snapshot.liste ?? null;
  return { ...structuredClone(snapshot), version: 2,
    entries: (snapshot.entries || []).map(row => ({ ...row, liste })),
    ops: (snapshot.ops || []).map(op => ({ ...op, liste })),
    listen: snapshot.listen || [],
    contexts: [{ liste, seq: snapshot.seq || 0, aliases: snapshot.aliases || [],
      ladenId: snapshot.ladenId ?? null, pendingLaden: snapshot.pendingLaden || null,
      vorschlaege: snapshot.vorschlaege, suggestionsAt: snapshot.suggestionsAt ?? null,
      suggestionsDirty: snapshot.suggestionsDirty || false }],
  };
}

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
          const request = indexedDB.open('rezeptify-einkauf', 2);
          request.onupgradeneeded = event => {
            const db = request.result, tx = request.transaction;
            if (event.oldVersion === 0) {
              db.createObjectStore('eintraege', { keyPath: 'uuid' });
              db.createObjectStore('outbox', { keyPath: 'op_id' });
              db.createObjectStore('meta', { keyPath: 'key' });
            }
            tx.objectStore('eintraege').createIndex('liste', 'liste');
            if (event.oldVersion === 1) {
              const rows = {};
              let pending = 3;
              for (const name of ['eintraege', 'outbox', 'meta']) tx.objectStore(name).getAll().onsuccess = e => {
                rows[name] = e.target.result;
                if (--pending) return;
                const migrated = migrateV1({ entries: rows.eintraege, ops: rows.outbox,
                  ...Object.fromEntries(rows.meta.map(row => [row.key, row.value])) });
                for (const row of migrated.entries) tx.objectStore('eintraege').put(row);
                for (const op of migrated.ops) tx.objectStore('outbox').put(op);
                for (const [key, value] of Object.entries(migrated)) if (!['entries', 'ops'].includes(key))
                  tx.objectStore('meta').put({ key, value });
              };
            }
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
  let initialized = false, initializing, ops = [], listen = [], contexts = new Map();
  const emptySuggestions = () => ({ faellig:[], haeufig:[], zuletzt:[], wochenplan:[] });
  function context(id = liste) {
    if (!contexts.has(id)) contexts.set(id, { liste:id, server:new Map(), state:new Map(), aliases:new Map(),
      seq:0, ladenId:null, pendingLaden:null, vorschlaege:emptySuggestions(), suggestionsAt:null, suggestionsDirty:false, polledAt:null });
    return contexts.get(id);
  }
  let kategorien = [], laeden = [], reihenfolgen = {}, catalogLoaded = false, catalogAt = 0;
  let artikel = [], artikelAt = 0;
  let articleRequest;
  let clock, geraet, liste = null, nr = 0, lastSync = null, fehler = null;
  let timer, running, retry = 0, batchSize = 200, writes = Promise.resolve(), disposed = false;
  const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
  const visible = () => typeof document === 'undefined' || document.visibilityState === 'visible';
  function emit(type) { events.dispatchEvent(new Event(type)); }
  function persist() {
    const current = context();
    const snapshot = { version:2, entries: [...contexts.values()].flatMap(ctx => [...ctx.server.values()].map(row => ({ ...row, liste:ctx.liste }))),
      ops:structuredClone(ops), listen, contexts:[...contexts.values()].map(({ server, state, aliases, suggestionRequest, ...ctx }) => ({ ...ctx, aliases:[...aliases] })),
      aliases:[...current.aliases], seq:current.seq, ladenId:current.ladenId, pendingLaden:current.pendingLaden,
      clock:clock.state(), geraet, liste, nr, lastSync, kategorien, laeden, reihenfolgen, artikel, artikelAt };
    writes = writes.then(() => storage.save(snapshot)).catch(() => toast('Offline-Speicher nicht verfügbar'));
    return writes;
  }
  function rebuild() {
    for (const ctx of contexts.values()) {
      const pending = ops.filter(op => op.liste === ctx.liste);
      const result = rebase(ctx.server, ctx.aliases, pending.map(({ nr, liste, ...op }) => op));
      ctx.state = result.state;
      const rewritten = new Map(result.pendingOps.map((op, i) => [op.op_id, { ...op, nr:pending[i].nr, liste:ctx.liste }]));
      ops = ops.map(op => rewritten.get(op.op_id) || op);
    }
    emit('change'); emit('status');
  }
  function pollDelay() { return 3000; }
  function scheduleSync(delay = 300) {
    clearTimeout(timer);
    if (disposed || !initialized || !visible() || !online()) return;
    timer = setTimeout(() => { sync(); }, delay);
    timer.unref?.();
  }
  function enqueue(typ, id, data, target = liste) {
    if (!initialized) throw new Error('Einkaufsliste wird geladen');
    const op = makeOp(clock, typ, id, data);
    const result = applyOpLocal(context(target).state, op);
    if (result.abgelehnt) throw new Error(result.abgelehnt);
    ops.push({ ...op, nr: ++nr, liste:target });
    persist(); emit('change'); emit('status'); scheduleSync(300);
    return result.ziel;
  }
  function rejectBatch(batch) {
    for (const op of batch) toast(`Änderung an ${context(op.liste).state.get(op.eintrag)?.name || op.daten.name || 'Einkaufsliste'} wurde verworfen`);
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
  async function refreshArticles(force = false) {
    if (!online() || (!force && artikelAt && now() - artikelAt < 6 * 3600000)) return;
    if (articleRequest) return articleRequest;
    articleRequest = (async () => {
      const data = await api('/api/einkauf/artikel?limit=500');
      artikel = data.artikel; artikelAt = now();
      emit('change'); await persist();
    })().finally(() => { articleRequest = null; });
    return articleRequest;
  }
  async function refreshSuggestions(force = false) {
    const ctx = context(), target = liste;
    if (!online() || (!force && ctx.suggestionsAt !== null && now() - ctx.suggestionsAt < 60000)) return;
    if (ctx.suggestionRequest) return ctx.suggestionRequest;
    ctx.suggestionsAt = now();
    ctx.suggestionRequest = (async () => {
      ctx.vorschlaege = await api('/api/einkauf/vorschlaege' + (target ? `?liste=${encodeURIComponent(target)}` : ''));
      ctx.suggestionsDirty = false;
      emit('change'); await persist();
    })().finally(() => { ctx.suggestionRequest = null; });
    return ctx.suggestionRequest;
  }
  async function flushLaden(ctx) {
    if (!ctx.pendingLaden || !ctx.liste) return;
    const pending = ctx.pendingLaden;
    await writes;
    try {
      await api(`/api/einkauf/listen/${ctx.liste}`, { method:'PATCH', body:JSON.stringify({ laden_id:pending.value }) });
    } catch (error) {
      if (error.status !== 404) throw error;
      toast('Laden nicht mehr vorhanden');
      if (ctx.pendingLaden === pending) ctx.ladenId = null;
    }
    if (ctx.pendingLaden === pending) ctx.pendingLaden = null;
    await persist();
  }
  function discover(answer, ctx) {
    if (ctx.liste === null) {
      contexts.delete(null); ctx.liste = answer.liste; contexts.set(ctx.liste, ctx);
      for (const op of ops) if (op.liste === null) op.liste = ctx.liste;
      if (liste === null) liste = ctx.liste;
    }
    if (answer.listen) {
      listen = answer.listen;
      for (const row of listen) {
        const target = context(row.uuid);
        if (!target.pendingLaden) target.ladenId = row.laden_id ?? null;
      }
      if (listen.length && !listen.some(row => row.uuid === liste)) liste = listen.find(row => row.ist_standard)?.uuid || listen[0].uuid;
    }
  }
  async function syncContext(ctx) {
    if (ctx.pendingLaden) await flushLaden(ctx);
    do {
      const batch = ops.filter(op => op.liste === ctx.liste).slice(0, batchSize);
      let answer;
      try {
        const current = clock.state();
        const hlc = `${String(current.ms).padStart(13, '0')}-${current.counter.toString(16).padStart(4, '0')}-${geraet}`;
        answer = await api('/api/einkauf/sync', { method:'POST', body:JSON.stringify({
          liste:ctx.liste, seit:ctx.seq, hlc, ops:batch.map(({ nr, liste, ...op }) => op),
        }) });
      } catch (error) {
        if (error.status === 413 && batch.length > 1) { batchSize = Math.max(1, Math.floor(batch.length / 2)); continue; }
        if (error.status >= 400 && error.status < 500 && error.status !== 401 && error.status !== 413) {
          rejectBatch(batch); rebuild(); await persist();
          if (ops.some(op => op.liste === ctx.liste)) continue;
        }
        throw error;
      }
      for (const row of answer.eintraege || []) ctx.server.set(row.uuid, row);
      for (const [id, row] of ctx.server) if (row.geloescht && Number(row.hlc_geloescht.slice(0, 13)) < now() - 30 * 86400000) ctx.server.delete(id);
      for (const alias of answer.aliase || []) ctx.aliases.set(alias.alt, alias.ziel);
      const results = answer.ergebnisse || [];
      rejectBatch(batch.filter(op => results.some(r => r.op_id === op.op_id && r.ergebnis === 'abgelehnt')));
      const confirmed = new Set(results.map(r => r.op_id));
      ops = ops.filter(op => !confirmed.has(op.op_id));
      if (ctx.seq !== answer.seq || results.some(result => result.ergebnis === 'ok')) ctx.suggestionsDirty = true;
      ctx.seq = answer.seq; ctx.polledAt = now(); clock.observe(answer.hlc);
      discover(answer, ctx);
      await flushLaden(ctx);
      lastSync = now();
      rebuild(); await persist();
      if (batch.length && !batch.some(op => confirmed.has(op.op_id))) break;
    } while (ops.some(op => op.liste === ctx.liste) && online());
  }
  async function run() {
    clearTimeout(timer);
    if (!initialized || !online()) { emit('status'); return; }
    let delay = pollDelay();
    try {
      await syncContext(context());
      // Always drain every list's outbox; idle background lists poll every 30 seconds.
      for (const ctx of contexts.values()) {
        if (ctx.liste === liste) continue;
        if (!listen.some(row => row.uuid === ctx.liste) && !ops.some(op => op.liste === ctx.liste) && !ctx.pendingLaden) continue;
        if (ctx.pendingLaden || ops.some(op => op.liste === ctx.liste) || (visible() && (ctx.polledAt === null || now() - ctx.polledAt >= 30000)))
          await syncContext(ctx);
      }
      fehler = null; retry = 0; emit('status');
      const learnedChanged = [...contexts.values()].some(ctx => ctx.suggestionsDirty);
      if (context().suggestionsDirty) {
        try { await refreshSuggestions(); } catch { /* Keep cached suggestions. */ }
      }
      // Purchases update last amounts on the server; refresh the article cache at most once a minute.
      const articlesStale = learnedChanged && (!artikelAt || now() - artikelAt > 60000);
      try { await refreshArticles(articlesStale); } catch { /* Keep cached articles. */ }
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
        const saved = migrateV1(await storage.load());
        geraet = saved?.geraet || crypto.randomUUID().replace(/-/g, '').slice(0, 20);
        clock = createClock(geraet, now, saved?.clock);
        liste = saved?.liste ?? null; ops = saved?.ops || [];
        nr = saved?.nr || 0; lastSync = saved?.lastSync || null; listen = saved?.listen || [];
        for (const cached of saved?.contexts || []) {
          const ctx = context(cached.liste);
          Object.assign(ctx, cached, { aliases:new Map(cached.aliases || []),
            server:new Map((saved?.entries || []).filter(row => row.liste === cached.liste).map(row => [row.uuid, row])),
            state:new Map(), vorschlaege:cached.vorschlaege || emptySuggestions() });
        }
        context();
        kategorien = saved?.kategorien || []; laeden = saved?.laeden || []; reihenfolgen = saved?.reihenfolgen || {};
        artikel = saved?.artikel || []; artikelAt = saved?.artikelAt || 0;
        initialized = true; rebuild(); await persist();
        if (online()) { try { await refreshCatalog(); } catch { /* Keep the cached catalog offline. */ } }
        try { await refreshArticles(); } catch { /* Keep cached articles. */ }
        globalThis.window?.addEventListener('online', connection);
        globalThis.window?.addEventListener('offline', connection);
        globalThis.window?.addEventListener('focus', wake);
        globalThis.document?.addEventListener('visibilitychange', wake);
        scheduleSync(0);
        return store;
      })();
      return initializing;
    },
    entries: (target = liste) => sortedEntries(context(target).state),
    liste: () => liste,
    listen: () => listen.map(row => ({ ...row, offen:context(row.uuid).polledAt !== null || context(row.uuid).state.size
      ? sortedEntries(context(row.uuid).state).filter(entry => !entry.erledigt).length : row.offen || 0 })),
    selectList(id) {
      if (!listen.some(row => row.uuid === id)) throw new Error('Liste nicht gefunden');
      liste = id; context(); persist(); emit('change'); scheduleSync(0);
      refreshSuggestions().catch(() => {});
    },
    async saveList(id, values) {
      if (!online()) throw new Error('Listen verwalten ist online möglich');
      const row = await api('/api/einkauf/listen' + (id ? `/${id}` : ''), { method:id ? 'PATCH' : 'POST', body:JSON.stringify(values) });
      const data = await api('/api/einkauf/listen');
      listen = data.listen;
      for (const item of listen) context(item.uuid);
      if (!id) liste = row.uuid;
      if (!listen.some(item => item.uuid === liste)) liste = listen.find(item => item.ist_standard)?.uuid || listen[0]?.uuid || null;
      persist(); emit('change'); scheduleSync(0);
      return row;
    },
    moveToList(id, target) {
      if (target === liste || !listen.some(row => row.uuid === target)) throw new Error('Andere Zielliste wählen');
      const row = context().state.get(id);
      if (!row || row.geloescht) throw new Error('Eintrag nicht gefunden');
      const data = Object.fromEntries(['name', 'menge', 'einheit', 'menge_text', 'notiz', 'kategorie_id', 'manuell', 'herkunft'].map(key => [key, row[key] ?? null]));
      const newId = enqueue('anlegen', crypto.randomUUID(), data, target);
      enqueue('loeschen', id, {});
      return newId;
    },
    artikel: () => structuredClone(artikel),
    vorschlaege: () => structuredClone(context().vorschlaege),
    refreshSuggestions, refreshArticles,
    async hideSuggestion(name, tage = 7) {
      await api('/api/einkauf/vorschlaege/ausblenden', { method:'POST', body:JSON.stringify({ name, tage }) });
      await Promise.all([refreshArticles(true), refreshSuggestions(true)]);
    },
    async setPantry(name, vorrat) {
      await api('/api/einkauf/artikel/vorrat', { method:'POST', body:JSON.stringify({ name, vorrat }) });
      await refreshArticles(true);
    },
    async addPlannedRecipes() {
      if (!online()) return;
      const target = liste;
      for (const recipe of context(target).vorschlaege.wochenplan) {
        const result = await api(`/api/rezepte/${Number(recipe.rezept_id)}/zu-einkaufsliste`, {
          method:'POST', body:JSON.stringify({ portionen:recipe.portionen, liste:target }),
        });
        if (result.vorrat?.length && typeof document !== 'undefined') {
          const { toastAction } = await import('./utils.js');
          toastAction(`${result.vorrat.map(item => item.name).join(', ')} vermutlich zuhause`, 'Trotzdem hinzufügen', () => {
            for (const item of result.vorrat) store.add(item.name, { menge_text:item.menge_text || null }, target);
          });
        }
      }
      await sync(); await refreshSuggestions(true);
    },
    kategorien: () => structuredClone(reihenfolgen[context().ladenId] || kategorien),
    laeden: () => structuredClone(laeden),
    ladenId: () => context().ladenId,
    setLaden(id) {
      context().ladenId = id; context().pendingLaden = { value: id };
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
      for (const ctx of contexts.values()) if (ctx.ladenId === id) { ctx.ladenId = null; ctx.pendingLaden = null; }
      await refreshCatalog();
    },
    async saveReihenfolge(id, ids) {
      await api(`/api/einkauf/laeden/${id}/reihenfolge`, { method: 'PUT', body: JSON.stringify({ kategorien: ids }) });
      await refreshCatalog();
    },
    kategorienFuer: id => structuredClone(reihenfolgen[id] || kategorien),
    setKategorie: (id, kategorie_id) => enqueue('inhalt_setzen', id, { kategorie_id }),
    status: () => ({ online: online(), pending: ops.length + [...contexts.values()].filter(ctx => ctx.pendingLaden).length, lastSync, fehler }),
    isInitialized: () => initialized,
    sync, scheduleSync,
    add(name, { menge = null, einheit = null, menge_text = null, notiz = null, herkunft = [], manuell = true } = {}, target = liste) {
      const existing = !menge_text && store.entries(target).find(row => !row.erledigt && !row.menge_text &&
        normalizeName(row.name) === normalizeName(name) && unitFamily(row.einheit) === unitFamily(einheit));
      if (existing) return enqueue('menge_plus', existing.uuid, { menge: menge ?? (unitFamily(einheit) === '' ? 1 : 0), einheit }, target);
      return enqueue('anlegen', crypto.randomUUID(), { name, menge, einheit, menge_text, notiz, herkunft, manuell,
        rang: rangNach([...context(target).state.values()].map(row => row.rang).sort().at(-1) ?? null) }, target);
    },
    restore(entry, target = liste) {
      const id = enqueue('anlegen', crypto.randomUUID(), {
        name: entry.name, menge: entry.menge, einheit: entry.einheit, menge_text: entry.menge_text,
        notiz: entry.notiz, herkunft: entry.herkunft || [], manuell: entry.manuell,
        rang: entry.rang, kategorie_id: entry.kategorie_id ?? null,
      }, target);
      if (entry.erledigt) store.setDone(id, true, target);
      return id;
    },
    toggle(id) { return store.setDone(id, !context().state.get(id)?.erledigt); },
    setDone: (id, erledigt, target = liste) => enqueue('status_setzen', id, { erledigt }, target),
    setAmount: (id, menge, einheit, menge_text) => enqueue('menge_setzen', id, { menge, einheit, menge_text }),
    plus: (id, delta, target = liste) => enqueue('menge_plus', id, { menge: delta, einheit: context(target).state.get(id)?.einheit ?? null }, target),
    rename: (id, name) => enqueue('inhalt_setzen', id, { name }),
    setNote: (id, notiz) => enqueue('inhalt_setzen', id, { notiz }),
    removeRecipe(rezeptId) {
      for (const row of store.entries()) if ((row.herkunft || []).some(origin => origin.rezept_id === rezeptId))
        enqueue('herkunft_entfernen', row.uuid, { rezept_id: rezeptId });
    },
    remove: (id, target = liste) => enqueue('loeschen', id, {}, target),
    move: (id, vorUuid, nachUuid) => enqueue('verschieben', id, { rang: rangZwischen(context().state.get(vorUuid)?.rang ?? null, context().state.get(nachUuid)?.rang ?? null) }),
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
