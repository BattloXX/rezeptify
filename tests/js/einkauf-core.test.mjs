import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';

// Node 20 treats .js as CommonJS without a package.json; load the browser ES module explicitly.
const source = await readFile(new URL('../../static/js/einkauf-core.js', import.meta.url), 'utf8');
const { createClock, parseHlc, compareHlc, rangZwischen, rangInitial, rangNach, normalizeName,
  unitFamily, unitMultiplier, applyOpLocal, rebase, makeOp, sortedEntries, formatAmount, groupByKategorie } =
  await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const fixture = JSON.parse(await readFile(new URL('../fixtures/rang_cases.json', import.meta.url), 'utf8'));
const hlc = (t = 0, device = 'geraetA') => `${1600000000000 + t}-0000-${device}`;
const op = (typ, eintrag, daten = {}, t = 10, device = 'geraetA') =>
  ({ op_id: randomUUID(), typ, eintrag, daten, hlc: hlc(t, device) });
function create(state, name = 'Milch', daten = {}, t = 0) {
  const id = randomUUID();
  assert.equal(applyOpLocal(state, op('anlegen', id, { name, ...daten }, t)).ziel, id);
  return id;
}
function apply(state, ...ops) {
  for (const operation of ops) assert.ok(!applyOpLocal(state, operation).abgelehnt);
}

test('HLC format, monotonicity, observe, persistence and overflow', () => {
  let now = 1700000000000;
  const clock = createClock('A_-9', () => now);
  const a = clock.tick(), b = clock.tick();
  assert.match(a, /^[0-9]{13}-[0-9a-f]{4}-[A-Za-z0-9_-]{1,36}$/);
  assert.ok(compareHlc(a, b) < 0);
  now--;
  assert.ok(clock.tick() > b);
  clock.observe('1700000001000-ffff-Z');
  assert.equal(clock.tick(), '1700000001001-0000-A_-9');
  const saved = clock.state();
  for (const invalid of ['bad', null, '1700000000000-ABCD-A', '1700000000000-0000-A\n', `${now + 86400001}-0000-A`]) clock.observe(invalid);
  assert.deepEqual(clock.state(), saved);
  const restored = createClock('A_-9', () => now, saved);
  assert.equal(restored.tick(), clock.tick());
  const copy = restored.state(); copy.ms = 0;
  assert.notEqual(restored.state().ms, 0);
  assert.equal(parseHlc(a).ms, 1700000000000);
  assert.throws(() => parseHlc('bad'), /hlc_format/);
  assert.throws(() => createClock('ä'), /geraet_format/);
  assert.throws(() => createClock('A\n'), /geraet_format/);
  assert.throws(() => createClock('A', () => 9999999999999, { ms: 9999999999999, counter: 65535 }).tick(), /hlc_ueberlauf/);
});

test('ranks match Python fixture', () => {
  for (const [a, b, expected] of fixture.rangZwischen) assert.equal(rangZwischen(a, b), expected);
  for (const [a, expected] of fixture.rangNach) assert.equal(rangNach(a), expected);
  for (const [i, expected] of fixture.rangInitial) assert.equal(rangInitial(i), expected);
  assert.throws(() => rangZwischen('a', 'a0'), /rang_kein_zwischenraum/);
  assert.throws(() => rangZwischen('b', 'a'), /rang_reihenfolge/);
  assert.throws(() => rangNach('!'), /rang_format/);
  assert.throws(() => rangNach('a\n'), /rang_format/);
  for (const i of [-1, 1.5, 62 ** 8]) assert.throws(() => rangInitial(i), /rang_index/);
});

test('2000 seeded random insertions and 5000 appends stay sorted and unique', () => {
  let seed = 42;
  const ranks = [];
  for (let n = 0; n < 2000; n++) {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    const i = seed % (ranks.length + 1);
    ranks.splice(i, 0, rangZwischen(ranks[i - 1] ?? null, ranks[i] ?? null));
  }
  assert.deepEqual(ranks, [...new Set(ranks)].sort());
  let last = null;
  for (let i = 0; i < 5000; i++) {
    const next = rangNach(last);
    assert.equal(next.length, 9);
    if (last) assert.ok(next > last);
    last = next;
  }
});

test('normalization and unit families mirror Python', () => {
  for (const [name, expected] of [['  MILCH\n  frisch ', 'milch frisch'], ['Straße', 'strasse'], ['ÄPFEL', 'äpfel'], [null, '']])
    assert.equal(normalizeName(name), expected);
  for (const [unit, expected] of [[null, ''], ['', ''], [' g. ', 'g'], ['kg', 'g'], ['l', 'ml'], ['ml', 'ml'], ['Stück', 'Stk'], ['stueck.', 'Stk'], ['EL', 'EL'], ['tl.', 'TL'], ['Bund', 'bund'], ['bund.', 'bund'], ['Dose', 'dose'], ['__proto__', '__proto__']])
    assert.equal(unitFamily(unit), expected);
  assert.equal(unitMultiplier('KG.'), 1000);
  assert.equal(unitMultiplier('l'), 1000);
  assert.equal(unitMultiplier('Bund'), 1);
});

test('K3 same entry and K4 status converges in both arrival orders', () => {
  const state = new Map(), id = create(state);
  apply(state, op('status_setzen', id, { erledigt: true }), op('status_setzen', id, { erledigt: true }, 10, 'geraetB'));
  assert.equal(state.size, 1); assert.equal(state.get(id).erledigt, true);
  for (const reverse of [false, true]) {
    const s = new Map(), ident = create(s);
    const ops = [op('status_setzen', ident, { erledigt: true }, 1), op('status_setzen', ident, { erledigt: false }, 2, 'geraetB')];
    apply(s, ...(reverse ? ops.reverse() : ops));
    assert.equal(s.get(ident).erledigt, false);
  }
});

test('K5 independent fields; content and position use their own LWW clocks', () => {
  const s = new Map(), id = create(s);
  apply(s, op('menge_setzen', id, { menge: 3, einheit: null, menge_text: null }),
    op('status_setzen', id, { erledigt: true }, 10, 'geraetB'),
    op('inhalt_setzen', id, { name: ' Brot ', notiz: 'Vollkorn', kategorie_id: 3 }, 20),
    op('inhalt_setzen', id, { name: 'Alt' }, 10));
  assert.equal(s.get(id).menge, 3); assert.equal(s.get(id).erledigt, true);
  assert.equal(s.get(id).name, 'Brot'); assert.equal(s.get(id).notiz, 'Vollkorn'); assert.equal(s.get(id).kategorie_id, 3);
});

test('K6 deltas, equality boundary, units, clamp and local set without delta replay', () => {
  const s = new Map(), id = create(s, 'Milch', { menge: 1 });
  const delta = op('menge_plus', id, { menge: 1 });
  apply(s, delta, op('menge_plus', id, { menge: 1 }, 10, 'geraetB'), delta);
  assert.equal(s.get(id).menge, 3);
  apply(s, op('menge_setzen', id, { menge: 2, einheit: 'kg', menge_text: null }, 20));
  apply(s, op('menge_plus', id, { menge: 500, einheit: 'g' }, 20));
  assert.equal(s.get(id).menge, 2.5); assert.equal(s.get(id).einheit, 'kg');
  apply(s, op('menge_plus', id, { menge: 99, einheit: 'g' }, 19));
  assert.equal(s.get(id).menge, 2.5);
  apply(s, op('menge_plus', id, { menge: -10, einheit: 'kg' }, 30));
  assert.equal(s.get(id).menge, 0);
  apply(s, op('menge_setzen', id, { menge: 1.5, einheit: 'kg', menge_text: null }, 25));
  assert.equal(s.get(id).menge, 1.5); assert.equal(s.get(id).einheit, 'kg');
});

test('K7 local merge, alias followup, origins, unknown units and text isolation', () => {
  const s = new Map(), id = create(s, 'Petersilie', { menge: 1, einheit: 'Bund', herkunft: [{ rezept_id: 1 }] });
  const alias = randomUUID();
  assert.deepEqual(applyOpLocal(s, op('anlegen', alias, { name: ' PETERSILIE ', menge: 2, einheit: 'bund.', herkunft: [{ rezept_id: 2 }] })), { ziel: id });
  apply(s, op('status_setzen', alias, { erledigt: true }, 20));
  assert.equal(s.size, 1); assert.equal(s.get(id).menge, 3); assert.equal(s.get(id).einheit, 'Bund');
  assert.equal(s.get(id).erledigt, true); assert.deepEqual(s.get(id).herkunft, [{ rezept_id: 1 }, { rezept_id: 2 }]);
  create(s, 'Petersilie', { menge_text: 'nach Bedarf' });
  create(s, 'Petersilie', { menge_text: 'nach Bedarf' });
  assert.equal(s.size, 3);
  const quantities = new Map(), milk = create(quantities, 'Milch', {}, 20);
  assert.equal(applyOpLocal(quantities, op('anlegen', randomUUID(), { name: 'Milch' }, 10)).ziel, milk);
  assert.equal(quantities.get(milk).menge, 2);
  apply(quantities, op('menge_setzen', milk, { menge: 5, einheit: null, menge_text: null }, 40));
  assert.equal(applyOpLocal(quantities, op('anlegen', randomUUID(), { name: 'Milch', herkunft: [{ rezept_id: 3 }] }, 30)).ziel, milk);
  assert.equal(quantities.get(milk).menge, 5);
  assert.deepEqual(quantities.get(milk).herkunft, [{ rezept_id: 3 }]);
});

test('K8 tombstone wins even against later recreation; K9 stale clear keeps reopened entries', () => {
  const s = new Map(), id = create(s);
  apply(s, op('loeschen', id), op('menge_setzen', id, { menge: 5, einheit: null, menge_text: null }, 20), op('anlegen', id, { name: 'Neu' }, 30));
  assert.equal(s.get(id).geloescht, true); assert.equal(s.get(id).name, 'Milch');
  const a = create(s, 'A'), b = create(s, 'B');
  apply(s, op('status_setzen', a, { erledigt: true }, 1), op('status_setzen', a, { erledigt: false }, 2), op('status_setzen', b, { erledigt: true }, 1));
  apply(s, op('erledigte_loeschen', null, { eintraege: [{ uuid: a, hlc_status: hlc(1) }, { uuid: b, hlc_status: hlc(1) }] }));
  assert.equal(s.get(a).geloescht, false); assert.equal(s.get(b).geloescht, true);
});

test('K11 independent positions and sorted view', () => {
  const s = new Map(), a = create(s, 'A'), b = create(s, 'B'), c = create(s, 'C'), d = create(s, 'D');
  apply(s, op('verschieben', a, { rang: 'a' }), op('verschieben', b, { rang: 'B' }), op('verschieben', c, { rang: 'B' }),
    op('status_setzen', c, { erledigt: true }), op('loeschen', d));
  assert.deepEqual(sortedEntries(s).map(e => e.uuid), [b, a, c]);
  apply(s, op('status_setzen', c, { erledigt: false }, 20));
  assert.deepEqual(sortedEntries(s).map(e => e.uuid), [b, c, a]);
});

test('invalid operations leave all state unchanged', () => {
  const s = new Map(), id = create(s, 'Milch', { menge: 1, einheit: 'kg' });
  const invalid = [op('unbekannt', id), op('status_setzen', id, { erledigt: 1 }), op('verschieben', id, { rang: '!' }),
    op('anlegen', randomUUID(), { name: '' }), op('menge_plus', id, { menge: NaN }),
    op('inhalt_setzen', id, { kategorie_id: [] }), op('menge_plus', id, { menge: 1, einheit: 'ml' }),
    op('menge_setzen', id, { menge: 1 }), op('anlegen', randomUUID(), { name: 'Milch', menge: 9999999, einheit: 'kg' }),
    { ...op('loeschen', id), hlc: 'bad' }, { ...op('loeschen', id), hlc: `${Date.now() + 86400000 + 60000}-0000-A` },
    { ...op('loeschen', id), op_id: 'invalid' }, op('inhalt_setzen', randomUUID(), { name: 'Unbekannt' }),
    op('erledigte_loeschen', null, { eintraege: [{ uuid: id, hlc_status: 'bad' }] })];
  const before = structuredClone(s);
  for (const operation of invalid) {
    assert.ok(applyOpLocal(s, operation).abgelehnt);
    assert.deepEqual(s, before);
  }
});

test('rebase resolves alias chains and clear targets without mutating inputs', () => {
  const s = new Map(), id = create(s);
  const old = randomUUID(), middle = randomUUID();
  const pending = [op('status_setzen', old, { erledigt: true }, 20), op('erledigte_loeschen', null, { eintraege: [{ uuid: old, hlc_status: hlc(20) }] }, 30)];
  const original = structuredClone(pending);
  const result = rebase([...s.values()], [{ alt: old, ziel: middle }, { alt: middle, ziel: id }], pending);
  assert.equal(result.pendingOps[0].eintrag, id); assert.equal(result.pendingOps[1].daten.eintraege[0].uuid, id);
  assert.equal(result.state.get(id).geloescht, true);
  assert.deepEqual(pending, original); assert.equal(s.get(id).geloescht, false);
});

test('rebase preserves pending operations, replays once, and excludes acknowledged operations', () => {
  const s = new Map(), id = create(s, 'Milch', { menge: 1 });
  const delta = op('menge_plus', id, { menge: 2 });
  const first = rebase([...s.values()], [], [delta, delta]);
  assert.equal(first.state.get(id).menge, 3);
  const next = rebase([...s.values()], [], first.pendingOps);
  assert.equal(next.state.get(id).menge, 3);
  const confirmed = rebase([...first.state.values()], [], []);
  assert.equal(confirmed.state.get(id).menge, 3); assert.deepEqual(confirmed.pendingOps, []);
  const alias = randomUUID();
  const creation = op('anlegen', alias, { name: 'MILCH' });
  const merged = rebase([...s.values()], [], [creation]);
  assert.equal(merged.state.get(id).menge, 2);
  assert.equal(rebase([...s.values()], [], merged.pendingOps).state.get(id).menge, 2);
  assert.equal(rebase([...merged.state.values()], [{ alt: alias, ziel: id }], [creation]).state.get(id).menge, 2);
});

test('operation factory and German amount display', () => {
  const clock = createClock('A', () => 1700000000000);
  const built = makeOp(clock, 'loeschen', randomUUID(), {});
  assert.match(built.op_id, /^[0-9a-f-]{36}$/); assert.equal(built.typ, 'loeschen'); assert.equal(built.hlc, '1700000000000-0000-A');
  for (const [entry, expected] of [[{ menge: 1.5, einheit: 'kg' }, '1,5 kg'], [{ menge: 2, name: 'Milch' }, '2 Milch'],
    [{ menge_text: 'nach Geschmack', name: 'Salz' }, 'nach Geschmack Salz'], [{ menge: 0, name: 'Salz' }, '0 Salz']])
    assert.equal(formatAmount(entry), expected);
});

test('recipe removal subtracts all matching origins, converts units and replays its negative delta', () => {
  const state = new Map();
  const origins = [{ rezept_id: 1, menge: '0,5', einheit: 'kg' }, { rezept_id: 1, menge: '100', einheit: 'g' },
    { rezept_id: 2, menge: '400', einheit: 'g' }];
  const id = create(state, 'Mehl', { menge: 1000, einheit: 'g', herkunft: origins });
  const removal = op('herkunft_entfernen', id, { rezept_id: 1 }, 30);
  assert.ok(!applyOpLocal(state, removal).abgelehnt);
  applyOpLocal(state, removal);
  applyOpLocal(state, op('herkunft_entfernen', id, { rezept_id: 1 }, 40));
  assert.equal(state.get(id).menge, 400);
  assert.deepEqual(state.get(id).herkunft, origins.slice(2));
  applyOpLocal(state, op('menge_setzen', id, { menge: 2, einheit: 'kg', menge_text: null }, 20));
  assert.equal(state.get(id).menge, 1400);
});

test('recipe removal respects manual entries, tombstones, missing quantities and newer sets', () => {
  for (const manual of [false, true]) for (const menge of [null, 2]) {
    const s = new Map(), id = create(s, 'Mehl', { menge, manuell: manual, herkunft: [{ rezept_id: 1, menge: menge == null ? 'etwas' : '2' }] });
    applyOpLocal(s, op('herkunft_entfernen', id, { rezept_id: 1 }, 20));
    assert.equal(s.get(id).geloescht, !manual);
    assert.equal(s.get(id).menge, menge == null ? null : 0);
  }
  const s = new Map(), id = create(s, 'Mehl', { menge: 2, herkunft: [{ rezept_id: 1, menge: '2' }] });
  applyOpLocal(s, op('menge_setzen', id, { menge: 8, einheit: null, menge_text: null }, 30));
  applyOpLocal(s, op('herkunft_entfernen', id, { rezept_id: 1 }, 20));
  assert.equal(s.get(id).menge, 8); assert.equal(s.get(id).geloescht, false); assert.deepEqual(s.get(id).herkunft, []);
  assert.equal(formatAmount({ menge: 1500, einheit: 'g', name: 'Mehl' }), '1,5 kg Mehl');
  assert.equal(formatAmount({ menge: 1250, einheit: 'ml', name: 'Milch' }), '1,25 l Milch');
});

test('recipe removal understands formatted mixed fractions and unquantified origins', () => {
  for (const [quantity, menge] of [['1½', 1.5], ['⅓', .33], ['1/2', .5], ['nach Geschmack', null]]) {
    const s = new Map(), id = create(s, 'Mehl', { menge, einheit:'kg', herkunft:[{ rezept_id:1, menge:quantity, einheit:'kg' }] });
    apply(s, op('herkunft_entfernen', id, { rezept_id:1 }));
    assert.equal(s.get(id).geloescht, true); assert.equal(s.get(id).menge, menge == null ? null : 0);
  }
});


test('category grouping preserves store order, rank order and hides empty/done/deleted groups', () => {
  const categories = [{ id:2, name:'Brot' }, { id:1, name:'Obst' }, { id:3, name:'Leer' }, { id:4, name:'Sonstiges' }];
  const rows = [
    { uuid:'a', name:'Apfel', rang:'Z', kategorie_id:1 },
    { uuid:'b', name:'Birne', rang:'A', kategorie_id:1 },
    { uuid:'c', name:'Brot', rang:'C', kategorie_id:2 },
    { uuid:'d', name:'Milch', rang:'D', kategorie_id:null },
    { uuid:'e', name:'Erledigt', rang:'E', kategorie_id:3, erledigt:true },
    { uuid:'f', name:'Gelöscht', rang:'F', kategorie_id:3, geloescht:true },
    { uuid:'g', name:'Unbekannt', rang:'G', kategorie_id:999 },
  ];
  const groups = groupByKategorie(rows, categories);
  assert.deepEqual(groups.map(g => g.id), [2, 1, 4]);
  assert.deepEqual(groups[1].entries.map(e => e.uuid), ['b', 'a']);
  assert.deepEqual(groups[2].entries.map(e => e.uuid), ['d', 'g']);
  assert.deepEqual(groupByKategorie([], categories), []);
  assert.equal(groupByKategorie(rows, []).length, 1);
  assert.equal(categories[0].entries, undefined);
});
