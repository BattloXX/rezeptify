// DOM-free shopping-list primitives shared by the offline client.
const HLC = /^([0-9]{13})-([0-9a-f]{4})-([A-Za-z0-9_-]{1,36})$/;
const DIGITS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
const HLC_FIELDS = ['hlc_inhalt', 'hlc_menge', 'hlc_status', 'hlc_position', 'hlc_geloescht'];
const local = new WeakMap();

function fail(reason) { throw new Error(reason); }

export function parseHlc(s) {
  const match = typeof s === 'string' && s.match(HLC);
  if (!match || match[0] !== s) fail('hlc_format');
  return { ms: Number(match[1]), counter: parseInt(match[2], 16), geraet: match[3] };
}

export function compareHlc(a, b) { return a < b ? -1 : a > b ? 1 : 0; }

export function createClock(geraetId, nowFn = Date.now, state = null) {
  if (typeof geraetId !== 'string' || !/^[A-Za-z0-9_-]{1,36}$/.test(geraetId) || geraetId.trim() !== geraetId) fail('geraet_format');
  let last = { ms: 0, counter: 0 };
  if (state && Number.isSafeInteger(state.ms) && state.ms >= 0 && state.ms <= 9999999999999 &&
      Number.isInteger(state.counter) && state.counter >= 0 && state.counter <= 0xffff) last = { ms: state.ms, counter: state.counter };
  return {
    tick() {
      let ms = Math.max(Math.floor(nowFn()), last.ms);
      let counter = ms === last.ms ? last.counter + 1 : 0;
      if (counter > 0xffff) { ms++; counter = 0; }
      if (ms > 9999999999999) fail('hlc_ueberlauf');
      last = { ms, counter };
      return `${String(ms).padStart(13, '0')}-${counter.toString(16).padStart(4, '0')}-${geraetId}`;
    },
    observe(hlc) {
      try {
        const seen = parseHlc(hlc);
        if (seen.ms <= nowFn() + 86400000 && (seen.ms > last.ms ||
            (seen.ms === last.ms && seen.counter > last.counter))) last = { ms: seen.ms, counter: seen.counter };
      } catch { /* Invalid remote clocks do not affect local time. */ }
    },
    state() { return { ...last }; },
  };
}

function rank(value) {
  if (typeof value !== 'string' || !/^[0-9A-Za-z]{1,64}$/.test(value) || value.trim() !== value) fail('rang_format');
  return value;
}

export function rangZwischen(a, b) {
  if (a !== null) rank(a);
  if (b !== null) rank(b);
  if (a !== null && b !== null && a >= b) fail('rang_reihenfolge');
  let prefix = '', lower = a || '', upper = b;
  for (;;) {
    const lo = lower ? DIGITS.indexOf(lower[0]) : -1;
    const hi = upper ? DIGITS.indexOf(upper[0]) : 62;
    if (upper === '') {
      const candidate = prefix.slice(0, -1);
      if (candidate && (a === null || a < candidate) && (b === null || candidate < b)) return rank(candidate);
      fail('rang_kein_zwischenraum');
    }
    if (hi - lo > 1) {
      let result = prefix + DIGITS[Math.floor((lo + hi) / 2)];
      if (result.endsWith('0')) result += 'U';
      return rank(result);
    }
    if (lo === hi) { prefix += lower[0]; lower = lower.slice(1); upper = upper.slice(1); }
    else if (lo === -1) { prefix += upper[0]; upper = upper.slice(1); }
    else { prefix += lower[0]; lower = lower.slice(1); upper = null; }
  }
}

function rankHead(value) {
  let result = '';
  for (let i = 0; i < 8; i++) {
    result = DIGITS[value % 62] + result;
    value = Math.floor(value / 62);
  }
  return result + 'U';
}

export function rangInitial(i) {
  if (!Number.isSafeInteger(i) || i < 0 || (i + 1) * 1024 >= 62 ** 8) fail('rang_index');
  return rankHead((i + 1) * 1024);
}

export function rangNach(a) {
  if (a === null) return rangInitial(0);
  rank(a);
  let value = 0;
  for (const char of (a.slice(0, 8) + '00000000').slice(0, 8)) value = value * 62 + DIGITS.indexOf(char);
  value = (Math.floor(value / 1024) + 1) * 1024;
  if (value < 62 ** 8) {
    const result = rankHead(value);
    if (result > a) return result;
  }
  return rangZwischen(a, null);
}

export function normalizeName(name) {
  return typeof name === 'string' ? name.trim().toLocaleLowerCase('de').replace(/ß/g, 'ss').replace(/ς/g, 'σ').replace(/\s+/gu, ' ') : '';
}

const UNITS = { g: ['g', 1], kg: ['g', 1000], ml: ['ml', 1], l: ['ml', 1000],
  stk: ['Stk', 1], 'stück': ['Stk', 1], stueck: ['Stk', 1], el: ['EL', 1], tl: ['TL', 1] };
function knownUnit(unit) {
  const key = typeof unit === 'string' ? unit.trim().toLowerCase().replace(/\.+$/, '') : '';
  return Object.hasOwn(UNITS, key) ? UNITS[key] : undefined;
}
export function unitFamily(unit) {
  return knownUnit(unit)?.[0] ?? normalizeName((unit || '').trim().replace(/\.+$/, ''));
}
export function unitMultiplier(unit) { return knownUnit(unit)?.[1] ?? 1; }

function uuid(value) {
  if (typeof value !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value) || value.trim() !== value) fail('uuid_format');
}
function number(value, nullable = false) {
  if (value === null && nullable) return;
  if (typeof value !== 'number') fail('menge_format');
  if (!Number.isFinite(value) || Math.abs(value) > 9999999.999) fail('menge_bereich');
}
const FIELDS = {
  anlegen: [['name', 'menge', 'einheit', 'menge_text', 'notiz', 'rang', 'herkunft', 'manuell', 'kategorie_id'], ['name']],
  inhalt_setzen: [['name', 'notiz', 'kategorie_id'], []],
  menge_setzen: [['menge', 'einheit', 'menge_text'], ['menge', 'einheit', 'menge_text']],
  herkunft_entfernen: [['rezept_id'], ['rezept_id']],
  menge_plus: [['menge', 'einheit'], ['menge']], status_setzen: [['erledigt'], ['erledigt']],
  verschieben: [['rang'], ['rang']], loeschen: [[], []], erledigte_loeschen: [['eintraege'], ['eintraege']],
};
function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
function validate(op) {
  if (!object(op) || Object.keys(op).some(k => !['op_id', 'typ', 'eintrag', 'hlc', 'daten'].includes(k))) fail('op_format');
  uuid(op.op_id);
  if (parseHlc(op.hlc).ms > Date.now() + 86400000) fail('hlc_zukunft');
  if (typeof op.typ !== 'string' || !Object.hasOwn(FIELDS, op.typ)) fail('typ_unbekannt');
  const data = op.daten, [allowed, required] = FIELDS[op.typ];
  if (!object(data) || Object.keys(data).some(k => !allowed.includes(k)) || required.some(k => !Object.hasOwn(data, k))) fail('daten_format');
  if (op.typ === 'erledigte_loeschen') {
    if (op.eintrag !== null && op.eintrag !== '') fail('eintrag_format');
    if (!Array.isArray(data.eintraege) || data.eintraege.length > 500) fail('eintraege_format');
    for (const entry of data.eintraege) {
      if (!object(entry) || Object.keys(entry).length !== 2 || !Object.hasOwn(entry, 'uuid') || !Object.hasOwn(entry, 'hlc_status')) fail('eintraege_format');
      uuid(entry.uuid); parseHlc(entry.hlc_status);
    }
  } else uuid(op.eintrag);
  for (const [key, limit] of [['name', 255], ['notiz', 255], ['einheit', 32], ['menge_text', 64]]) {
    if (!Object.hasOwn(data, key) || (key !== 'name' && data[key] === null)) continue;
    if (typeof data[key] !== 'string' || [...data[key]].length > limit || (key === 'name' && !data[key].trim())) fail(key + '_format');
  }
  if (Object.hasOwn(data, 'menge')) number(data.menge, op.typ !== 'menge_plus');
  if (Object.hasOwn(data, 'rang')) rank(data.rang);
  for (const key of ['erledigt', 'manuell']) if (Object.hasOwn(data, key) && typeof data[key] !== 'boolean') fail(key + '_format');
  if (Object.hasOwn(data, 'herkunft') && !Array.isArray(data.herkunft)) fail('herkunft_format');
  if (Object.hasOwn(data, 'rezept_id') && (!Number.isInteger(data.rezept_id) || data.rezept_id <= 0 || data.rezept_id > 2147483647)) fail('rezept_id_format');
  if (Object.hasOwn(data, 'kategorie_id') && data.kategorie_id !== null &&
      (!Number.isInteger(data.kategorie_id) || data.kategorie_id <= 0 || data.kategorie_id > 2147483647)) fail('kategorie_id_format');
  // JSON persistence must not silently drop values or turn non-finite numbers into null.
  const seen = new Set();
  function jsonValue(value) {
    if (value === null || typeof value === 'string' || typeof value === 'boolean') return;
    if (typeof value === 'number' && Number.isFinite(value)) return;
    if (typeof value !== 'object' || seen.has(value)) fail('daten_format');
    seen.add(value);
    for (const item of Object.values(value)) jsonValue(item);
    seen.delete(value);
  }
  jsonValue(data);
}

function amountPlus(row, amount, unit) {
  const family = unitFamily(row.einheit);
  if (row.menge_text || family !== unitFamily(unit)) fail('einheit_inkompatibel');
  const old = row.menge ?? (family === '' ? 1 : 0);
  const total = Math.max(0, old * unitMultiplier(row.einheit) + amount * unitMultiplier(unit));
  // Keep the entry's own unit (2 kg + 500 g = 2.5 kg), never switch silently to the base unit.
  const einheit = row.einheit && row.einheit.trim() ? row.einheit : (unit || null);
  const menge = Math.round(total / unitMultiplier(einheit) * 1000) / 1000;
  number(menge);
  return { menge, einheit };
}
function metadata(state) {
  if (!local.has(state)) local.set(state, { aliases: new Map(), applied: new Map(), deltas: [] });
  return local.get(state);
}
function resolve(ident, aliases) {
  const visited = new Set();
  while (aliases.has(ident)) {
    if (visited.has(ident)) fail('alias_zyklus');
    visited.add(ident); ident = aliases.get(ident);
  }
  return ident;
}

export function applyOpLocal(state, op) {
  try {
    validate(op);
    const meta = metadata(state);
    if (meta.applied.has(op.op_id)) return { ...meta.applied.get(op.op_id) };
    const { typ, hlc, daten: data } = op;
    let ident = resolve(op.eintrag, meta.aliases);
    const row = state.get(ident);
    if (typ === 'erledigte_loeschen') {
      const entries = data.eintraege.map(item => [resolve(item.uuid, meta.aliases), item.hlc_status]);
      for (const [id, status] of entries) {
        const entry = state.get(id);
        if (entry && !entry.geloescht && entry.erledigt && entry.hlc_status <= status)
          state.set(id, { ...entry, geloescht: true, hlc_geloescht: hlc });
      }
    } else if (row && (row.geloescht || typ === 'anlegen')) {
      // Existing UUIDs and tombstones cannot be recreated.
    } else if (typ === 'anlegen') {
      const family = unitFamily(data.einheit);
      const target = !data.menge_text && [...state.values()].find(e => !e.geloescht && !e.erledigt &&
        normalizeName(e.name) === normalizeName(data.name) && !e.menge_text && unitFamily(e.einheit) === family);
      if (target) {
        const amount = data.menge ?? (family === '' ? 1 : 0);
        // On live entries hlc_geloescht still records creation; only a set advances hlc_menge.
        const newerSet = target.hlc_menge > target.hlc_geloescht && target.hlc_menge > hlc;
        const values = newerSet ? {} : amountPlus(target, amount, data.einheit);
        state.set(target.uuid, { ...target, ...values, manuell: target.manuell || !!data.manuell, herkunft: [...(target.herkunft || []), ...structuredClone(data.herkunft || [])] });
        meta.aliases.set(ident, target.uuid);
        ident = target.uuid;
      } else {
        const ranks = [...state.values()].map(e => e.rang).filter(r => r != null).sort();
        const entry = { uuid: ident, name: data.name.trim(), notiz: null, menge: null, einheit: null,
          menge_text: null, erledigt: false, manuell: false, herkunft: [], kategorie_id: null, geloescht: false,
          ...structuredClone(data), rang: data.rang ?? rangNach(ranks.at(-1) ?? null) };
        entry.name = data.name.trim();
        for (const field of HLC_FIELDS) entry[field] = hlc;
        state.set(ident, entry);
      }
    } else if (!row) fail('eintrag_nicht_gefunden');
    else if (typ === 'menge_plus') {
      if (hlc >= row.hlc_menge) state.set(ident, { ...row, ...amountPlus(row, data.menge, data.einheit) });
    } else if (typ === 'herkunft_entfernen') {
      const removed = (row.herkunft || []).filter(origin => origin.rezept_id === data.rezept_id);
      const herkunft = (row.herkunft || []).filter(origin => origin.rezept_id !== data.rezept_id);
      const values = { herkunft };
      if (removed.length && hlc >= row.hlc_menge) {
        let delta = 0;
        for (const origin of removed) {
          const raw = String(origin.menge ?? '').trim().replace(',', '.');
          let amount = /^[0-9]+(?:\.[0-9]+)?$/.test(raw) ? Number(raw) : NaN;
          const fraction = raw.match(/^(?:(\d+)\s+)?(\d+)\/(\d+)$/);
          if (fraction) amount = Number(fraction[1] || 0) + Number(fraction[2]) / Number(fraction[3]);
          const fractions = { '½':0.5, '¼':0.25, '¾':0.75, '⅓':0.33, '⅔':0.67 };
          const mixed = raw.match(/^(\d*)([½¼¾⅓⅔])$/u);
          if (mixed) amount = Number(mixed[1] || 0) + fractions[mixed[2]];
          if (Number.isFinite(amount) && unitFamily(origin.einheit) === unitFamily(row.einheit))
            delta += amount * unitMultiplier(origin.einheit) / unitMultiplier(row.einheit);
        }
        if (delta) meta.deltas.push({ id: ident, hlc, amount: -delta, unit: row.einheit });
        if (row.menge != null) values.menge = Math.max(0, row.menge - delta);
        if (!herkunft.length && !row.manuell && (row.menge == null || values.menge <= 0)) {
          values.geloescht = true; values.hlc_geloescht = hlc;
        }
      }
      state.set(ident, { ...row, ...values });
    } else if (typ === 'loeschen') state.set(ident, { ...row, geloescht: true, hlc_geloescht: hlc });
    else {
      const field = { inhalt_setzen: 'hlc_inhalt', menge_setzen: 'hlc_menge', status_setzen: 'hlc_status', verschieben: 'hlc_position' }[typ];
      if (hlc > row[field]) {
        const values = structuredClone(data);
        if (typ === 'menge_setzen' && !values.menge_text) {
          const deltas = meta.deltas.filter(delta => delta.id === ident && delta.hlc > hlc && unitFamily(delta.unit) === unitFamily(values.einheit));
          if (deltas.length) {
            const total = (values.menge ?? (unitFamily(values.einheit) === '' ? 1 : 0)) * unitMultiplier(values.einheit) +
              deltas.reduce((sum, delta) => sum + delta.amount * unitMultiplier(delta.unit), 0);
            values.menge = Math.max(0, total); values.einheit = knownUnit(values.einheit)?.[0] ?? values.einheit;
          }
        }
        if (typ === 'inhalt_setzen' && Object.hasOwn(values, 'name')) values.name = values.name.trim();
        state.set(ident, { ...row, ...values, [field]: hlc });
      }
    }
    const result = { ziel: typ === 'erledigte_loeschen' ? null : ident };
    meta.applied.set(op.op_id, result);
    return { ...result };
  } catch (error) { return { abgelehnt: error.message }; }
}

// pendingOps contains only unacknowledged operations; acknowledgements are removed by the store.
export function rebase(serverEntries, aliase, pendingOps) {
  const state = new Map([...serverEntries.values()].map(entry => [entry.uuid, structuredClone(entry)]));
  const aliases = new Map(aliase instanceof Map ? aliase : aliase.map(a => [a.alt, a.ziel]));
  for (const ident of aliases.keys()) resolve(ident, aliases);
  metadata(state).aliases = aliases;
  const rewritten = pendingOps.map(original => {
    const op = structuredClone(original);
    if (op.eintrag) op.eintrag = resolve(op.eintrag, aliases);
    if (op.typ === 'erledigte_loeschen') for (const item of op.daten.eintraege) item.uuid = resolve(item.uuid, aliases);
    return op;
  });
  for (const op of rewritten) applyOpLocal(state, op);
  return { state, pendingOps: rewritten };
}

export function makeOp(clock, typ, eintrag, daten) {
  return { op_id: crypto.randomUUID(), typ, eintrag, hlc: clock.tick(), daten };
}

export function sortedEntries(state) {
  return [...state.values()].filter(e => !e.geloescht).sort((a, b) =>
    Number(a.erledigt) - Number(b.erledigt) || compareHlc(a.rang ?? '', b.rang ?? '') || compareHlc(a.name, b.name));
}

export function formatAmount(entry) {
  let value = entry.menge, unit = entry.einheit;
  if (!entry.menge_text && value >= 1000 && ['g', 'ml'].includes(unit?.toLowerCase())) {
    value /= 1000; unit = unit.toLowerCase() === 'g' ? 'kg' : 'l';
  }
  const amount = entry.menge_text || (value == null ? null : String(Number(value.toFixed(6))).replace('.', ','));
  return [amount, unit, entry.name].filter(v => v !== null && v !== undefined && v !== '').join(' ');
}


export function groupByKategorie(entries, kategorienSortiert) {
  const groups = kategorienSortiert.map(category => ({ ...category, entries: [] }));
  const byId = new Map(groups.map(group => [group.id, group]));
  let fallback = groups.find(group => group.name === 'Sonstiges');
  for (const entry of sortedEntries(new Map(entries.map(row => [row.uuid, row])))) {
    if (entry.erledigt) continue;
    let group = byId.get(entry.kategorie_id);
    if (!group) {
      if (!fallback) { fallback = { id: null, name: 'Sonstiges', icon: 'category', entries: [] }; groups.push(fallback); }
      group = fallback;
    }
    group.entries.push(entry);
  }
  return groups.filter(group => group.entries.length);
}


export function rankAutocomplete(query, articles, entries = []) {
  const needle = normalizeName(query);
  if (!needle) return [];
  const candidates = new Map();
  for (const article of articles) candidates.set(normalizeName(article.anzeigename), { ...article, name:article.anzeigename });
  for (const entry of entries) {
    const key = normalizeName(entry.name);
    if (!candidates.has(key)) candidates.set(key, { name:entry.name, letzte_menge:entry.menge, letzte_einheit:entry.einheit, anzahl_gekauft:0 });
  }
  return [...candidates.values()].map(item => {
    const name = normalizeName(item.name);
    const score = name.startsWith(needle) ? 0 : name.split(/\s+/u).some(word => word.startsWith(needle)) ? 1 : name.includes(needle) ? 2 : 3;
    return { item, score };
  }).filter(({ score }) => score < 3).sort((a, b) => a.score - b.score ||
    (b.item.anzahl_gekauft || 0) - (a.item.anzahl_gekauft || 0) || a.item.name.localeCompare(b.item.name, 'de'))
    .slice(0, 6).map(({ item }) => item);
}
