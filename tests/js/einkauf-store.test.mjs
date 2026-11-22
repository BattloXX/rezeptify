import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { webcrypto } from 'node:crypto';

if (!globalThis.crypto) globalThis.crypto = webcrypto;
const moduleUrl = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const coreUrl = moduleUrl(await readFile(new URL('../../static/js/einkauf-core.js', import.meta.url), 'utf8'));
const core = await import(coreUrl);
const source = await readFile(new URL('../../static/js/einkauf-store.js', import.meta.url), 'utf8');
const { createStore, createStorage } = await import(moduleUrl(source.replace("'./einkauf-core.js'", JSON.stringify(coreUrl))));
const now = 1700000000000;

async function setup(t, handler, saved = null) {
  let connected = false;
  const calls = [], delays = [], messages = [];
  t.mock.method(globalThis, 'setTimeout', (fn, delay) => { delays.push(delay); return { unref() {} }; });
  t.mock.method(globalThis, 'clearTimeout', () => {});
  const original = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { get onLine() { return connected; } } });
  t.after(() => {
    if (original) Object.defineProperty(globalThis, 'navigator', original);
    else delete globalThis.navigator;
  });
  let snapshot = saved;
  const server = new Map();
  const store = createStore({
    now: () => now,
    storage: { load: async () => snapshot, save: async data => { snapshot = structuredClone(data); } },
    toast: msg => messages.push(msg),
    api: async (path, opts) => {
      if (path.startsWith('/api/einkauf/artikel?')) return { artikel:[] };
      if (path.startsWith('/api/einkauf/vorschlaege')) return { faellig:[], haeufig:[], zuletzt:[], wochenplan:[] };
      if (path === '/api/einkauf/kategorien') return { kategorien: [] };
      if (path === '/api/einkauf/laeden') return { laeden: [] };
      assert.equal(path, '/api/einkauf/sync');
      const request = JSON.parse(opts.body);
      calls.push(request);
      if (handler) return handler(request, calls.length, server);
      for (const op of request.ops) assert.ok(!core.applyOpLocal(server, op).abgelehnt);
      return answer(request, [...server.values()]);
    },
  });
  await store.init();
  t.after(() => store.dispose());
  return { store, calls, delays, messages, connect: () => { connected = true; }, snapshot: () => snapshot };
}
function answer(request, entries = [], extra = {}) {
  return { liste: 'standard', seq: 1, hlc: `${now}-1000-server`, eintraege: entries, aliase: [],
    ergebnisse: request.ops.map(op => ({ op_id: op.op_id, ergebnis: 'ok' })), ...extra };
}

test('offline operations are optimistic, persisted and sent in order; concurrent syncs share one run', async t => {
  const { store, calls, connect, snapshot } = await setup(t);
  const id = store.add('Milch', { menge: 1, einheit: 'l' });
  store.plus(id, 1);
  store.toggle(id);
  assert.equal(store.entries()[0].erledigt, true);
  assert.equal(store.status().pending, 3);
  await store.sync();
  assert.equal(calls.length, 0);
  connect();
  const first = store.sync();
  assert.equal(store.sync(), first);
  await first;
  assert.deepEqual(calls[0].ops.map(op => op.typ), ['anlegen', 'menge_plus', 'status_setzen']);
  assert.equal(calls[0].seit, 0);
  assert.equal(calls[0].ops[0].nr, undefined);
  assert.equal(store.entries()[0].menge, 2);
  assert.equal(store.status().pending, 0);
  assert.equal(snapshot().ops.length, 0);
  assert.equal(snapshot().seq, 1);
});

test('IndexedDB absence falls back to memory and warns once', async () => {
  const messages = [];
  const storage = createStorage(msg => messages.push(msg));
  const store = createStore({ storage, toast: () => {}, now: () => now });
  await store.init();
  const id = store.add('Brot');
  await store.dispose();
  const loaded = await storage.load();
  assert.equal(loaded.ops[0].eintrag, id);
  assert.equal(loaded.geraet.length, 20);
  assert.deepEqual(messages, ['Offline-Speicher nicht verfügbar']);
});

test('aliases rebase edits made while a create request is in flight', async t => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const target = crypto.randomUUID();
  const { store, calls, connect, snapshot } = await setup(t, async (request, count) => {
    if (count === 1) {
      await gate;
      const rowState = new Map();
      const op = request.ops[0];
      core.applyOpLocal(rowState, { ...op, eintrag: target });
      return answer(request, [...rowState.values()], { aliase: [{ alt: op.eintrag, ziel: target }] });
    }
    assert.equal(request.ops[0].eintrag, target);
    return answer(request);
  });
  const id = store.add('Milch');
  connect();
  const running = store.sync();
  store.rename(id, 'Hafermilch');
  release();
  await running;
  assert.equal(calls.length, 2);
  assert.equal(store.entries()[0].uuid, target);
  assert.deepEqual(snapshot().aliases, [[id, target]]);
});

test('rejected and ignored operations are acknowledged and removed', async t => {
  const { store, connect, messages } = await setup(t, request => answer(request, [], {
    ergebnisse: request.ops.map((op, i) => ({ op_id: op.op_id, ergebnis: i ? 'ignoriert' : 'abgelehnt' })),
  }));
  store.add('Brot'); store.add('Butter');
  connect(); await store.sync();
  assert.equal(store.status().pending, 0);
  assert.deepEqual(store.entries(), []);
  assert.deepEqual(messages, ['Änderung an Brot wurde verworfen']);
});

test('network failures back off from 2 seconds to 60 seconds without losing operations', async t => {
  const { store, connect, delays } = await setup(t, () => { throw new TypeError('Netzfehler'); });
  store.add('Brot'); connect();
  const retries = [];
  for (let i = 0; i < 7; i++) { await store.sync(); retries.push(delays.at(-1)); }
  assert.deepEqual(retries, [2000, 4000, 8000, 16000, 32000, 60000, 60000]);
  assert.equal(store.status().pending, 1);
  assert.equal(store.status().fehler, 'Netzfehler');
});

test('more than 200 pending operations drain in two requests', async t => {
  const { store, calls, connect } = await setup(t);
  for (let i = 0; i < 205; i++) store.add('Artikel ' + i);
  connect(); await store.sync();
  assert.deepEqual(calls.map(request => request.ops.length), [200, 5]);
  assert.equal(store.status().pending, 0);
  assert.equal(store.entries().length, 205);
});

test('HTTP 413 halves a batch and keeps operation order', async t => {
  const { store, calls, connect } = await setup(t, request => {
    if (request.ops.length > 2) throw Object.assign(new Error('Zu groß'), { status: 413 });
    return answer(request);
  });
  for (let i = 0; i < 5; i++) store.add('Artikel ' + i);
  connect(); await store.sync();
  assert.deepEqual(calls.map(request => request.ops.length), [5, 2, 2, 1]);
  assert.deepEqual(calls.slice(1).flatMap(request => request.ops.map(op => op.op_id)), calls[0].ops.map(op => op.op_id));
  assert.equal(store.status().pending, 0);
});

test('HTTP 400 discards a bad batch and continues with remaining operations', async t => {
  const { store, calls, connect, messages } = await setup(t, (request, count) => {
    if (count === 1) throw Object.assign(new Error('Ungültig'), { status: 400 });
    return answer(request);
  });
  for (let i = 0; i < 201; i++) store.add('Artikel ' + i);
  connect(); await store.sync();
  assert.deepEqual(calls.map(request => request.ops.length), [200, 1]);
  assert.equal(store.status().pending, 0);
  assert.equal(messages.length, 200);
});

test('restored pending state, duplicate amounts, conditional clear and undo use new operations', async t => {
  const first = await setup(t);
  const id = first.store.add('Milch', { menge: 1, einheit: 'l', notiz: 'kalt' });
  assert.equal(first.store.add('Milch', { menge: 500, einheit: 'ml' }), id);
  assert.equal(first.store.entries()[0].menge, 1.5);
  assert.equal(first.store.entries()[0].einheit, 'l');
  first.store.toggle(id);
  await first.store.dispose();
  const second = await setup(t, undefined, first.snapshot());
  assert.equal(second.store.status().pending, 3);
  const row = second.store.entries()[0];
  second.store.clearDone();
  assert.equal(second.store.entries().length, 0);
  const newId = second.store.restore(row);
  assert.notEqual(newId, id);
  assert.equal(second.store.entries()[0].notiz, 'kalt');
  assert.equal(second.store.entries()[0].erledigt, true);
  await second.store.dispose();
  const ops = second.snapshot().ops;
  assert.deepEqual(ops[3].daten.eintraege, [{ uuid: id, hlc_status: row.hlc_status }]);
  assert.equal(ops[4].typ, 'anlegen');
  assert.equal(ops[4].eintrag, newId);
});

test('removeRecipe queues one operation per matching entry, including done entries', async t => {
  const { store, snapshot } = await setup(t);
  const origin = [{ rezept_id: 7, menge: '2' }];
  const first = store.add('Eier', { menge: 2, herkunft: origin, manuell: false });
  store.add('Brot', { herkunft: origin, manuell: false });
  store.add('Salz');
  store.toggle(first);
  store.removeRecipe(7);
  assert.deepEqual(store.entries().map(e => e.name), ['Salz']);
  await store.dispose();
  assert.equal(snapshot().ops.filter(op => op.typ === 'herkunft_entfernen').length, 2);
});


test('catalog and shop choice survive offline reload and retry a failed PATCH', async t => {
  const cached = {
    kategorien: [{ id:1, name:'Obst', rang:'A' }],
    laeden: [{ id:4, name:'Markt', aktiv:true }],
    reihenfolgen: { 4:[{ id:1, name:'Obst', rang:'B' }] }, liste:'standard',
  };
  const first = await setup(t, undefined, cached);
  first.store.setLaden(4);
  await first.store.dispose();
  let snapshot = first.snapshot(), attempts = 0;
  const paths = [];
  const store = createStore({ now:() => now, toast:() => {},
    storage:{ load:async () => snapshot, save:async data => { snapshot = structuredClone(data); } },
    api:async (path, opts) => {
      paths.push(path);
      if (path === '/api/einkauf/listen/standard') {
        assert.deepEqual(JSON.parse(opts.body), { laden_id:4 });
        if (++attempts === 1) throw new Error('offline');
        return {};
      }
      if (path.startsWith('/api/einkauf/artikel?')) return { artikel:[] };
      if (path.startsWith('/api/einkauf/vorschlaege')) return { faellig:[], haeufig:[], zuletzt:[], wochenplan:[] };
      if (path === '/api/einkauf/kategorien') return { kategorien:cached.kategorien };
      if (path === '/api/einkauf/laeden') return { laeden:cached.laeden };
      if (path.includes('?laden=')) return { kategorien:cached.reihenfolgen[4] };
      return answer(JSON.parse(opts.body), [], { listen:[{ uuid:'standard', laden_id:4 }] });
    },
  });
  await store.init();
  assert.equal(store.ladenId(), 4);
  assert.equal(store.kategorien()[0].rang, 'B');
  first.connect();
  await store.sync();
  assert.equal(store.status().pending, 1);
  await store.sync();
  assert.equal(store.status().pending, 0);
  assert.equal(snapshot.pendingLaden, null);
  assert.equal(snapshot.ladenId, 4);
  assert.equal(attempts, 2);
  await store.dispose();
});


test('article and suggestion caches survive offline reload, throttle refresh and retry dirty suggestions after 60 seconds', async t => {
  let connected = true, time = now, snapshot, serverSeq = 1;
  const calls = [];
  const original = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', { configurable:true, value:{ get onLine() { return connected; } } });
  t.after(() => original ? Object.defineProperty(globalThis, 'navigator', original) : delete globalThis.navigator);
  t.mock.method(globalThis, 'setTimeout', () => ({ unref() {} }));
  t.mock.method(globalThis, 'clearTimeout', () => {});
  const options = { now:() => time, storage:{ load:async () => snapshot, save:async data => { snapshot = structuredClone(data); } },
    api:async (path, opts) => {
      calls.push(path);
      if (path.startsWith('/api/einkauf/artikel?')) return { artikel:[{ anzeigename:'Milch', letzte_menge:2 }] };
      if (path.startsWith('/api/einkauf/vorschlaege')) return { faellig:[{ anzeigename:'Milch' }], haeufig:[], zuletzt:[], wochenplan:[] };
      if (path === '/api/einkauf/kategorien') return { kategorien:[] };
      if (path === '/api/einkauf/laeden') return { laeden:[] };
      return answer(JSON.parse(opts.body), [], { seq:serverSeq });
    },
  };
  const store = createStore(options);
  await store.init();
  assert.equal(store.artikel()[0].anzeigename, 'Milch');
  await store.refreshSuggestions();
  const count = prefix => calls.filter(path => path.startsWith(prefix)).length;
  assert.equal(count('/api/einkauf/vorschlaege'), 1);
  await store.sync(); // changed seq, but the previous request is still within 60 seconds
  assert.equal(count('/api/einkauf/vorschlaege'), 1);
  time += 60001;
  await store.sync(); // no new changes: the dirty cache must still be refreshed
  assert.equal(count('/api/einkauf/vorschlaege'), 2);
  // Changes (purchases) refresh the article cache too, at most once a minute.
  assert.equal(count('/api/einkauf/artikel?'), 2);
  await store.sync(); // nothing changed: no further article request
  assert.equal(count('/api/einkauf/artikel?'), 2);
  time += 6 * 3600000;
  await store.sync();
  assert.equal(count('/api/einkauf/artikel?'), 3);
  await store.dispose();
  connected = false;
  const restored = createStore(options);
  await restored.init();
  assert.equal(restored.artikel()[0].letzte_menge, 2);
  assert.equal(restored.vorschlaege().faellig[0].anzeigename, 'Milch');
  const before = calls.length;
  await restored.refreshSuggestions(); await restored.refreshArticles();
  assert.equal(calls.length, before);
  await restored.dispose();
});
