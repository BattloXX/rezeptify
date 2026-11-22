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
  assert.equal(store.entries()[0].menge, 2000);
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
  assert.equal(first.store.entries()[0].menge, 1500);
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
