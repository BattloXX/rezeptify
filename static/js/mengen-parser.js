// Keep grammar and canonical units aligned with services/mengen_parser.py.
const UNITS = { g:'g', kg:'kg', mg:'mg', ml:'ml', cl:'cl', dl:'dl', l:'l', stk:'Stk', stück:'Stk', stücke:'Stk', el:'EL', tl:'TL', pkg:'Pkg', packung:'Pkg', packungen:'Pkg', pck:'Pkg', bund:'Bund', bünde:'Bund', dose:'Dose', dosen:'Dosen', becher:'Becher', flasche:'Flasche', flaschen:'Flaschen', glas:'Glas', gläser:'Gläser', kiste:'Kiste', kisten:'Kisten', netz:'Netz', netze:'Netze', beutel:'Beutel', prise:'Prise', prisen:'Prisen', zehe:'Zehe', zehen:'Zehen', scheibe:'Scheibe', scheiben:'Scheiben', rolle:'Rolle', rollen:'Rollen' };
const NUM = String.raw`(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?|[½¼¾⅓⅔])`;
const QTY = `${NUM}(?:\\s*[-–]\\s*${NUM})?`;
const UNIT = Object.keys(UNITS).sort((a, b) => b.length - a.length).join('|');
const PREFIX = new RegExp(`^(${QTY})(?:\\s*[x×]\\s*|\\s*(${UNIT})\\.?(?=\\s|$)\\s*|\\s+)(.+)$`, 'iu');
const SUFFIX = new RegExp(`^(.+?)\\s+(?:[x×]\\s*(${QTY})|(${QTY})(?:\\s*[x×]|\\s*(${UNIT})\\.?)?)$`, 'iu');
const FRACTIONS = { '½':0.5, '¼':0.25, '¾':0.75, '⅓':1/3, '⅔':2/3 };
function numeric(value) {
  if (Object.hasOwn(FRACTIONS, value)) return FRACTIONS[value];
  if (value.includes('/')) {
    const parts = value.split(/\s+/), fraction = parts.pop().split('/');
    return (parts.length ? Number(parts[0]) : 0) + Number(fraction[0]) / Number(fraction[1]);
  }
  return Number(value.replace(',', '.'));
}

export function parseEintrag(text) {
  const notes = [];
  let name = text.replace(/\(([^()]*)\)/gu, (_, note) => { if (note.trim()) notes.push(note.trim()); return ' '; }).replace(/\s+/gu, ' ').trim();
  let quantity = null, unit = null;
  const prefix = name.match(PREFIX), suffix = prefix ? null : name.match(SUFFIX);
  if (prefix) { quantity = prefix[1]; unit = prefix[2]; name = prefix[3].trim(); }
  else if (suffix) { name = suffix[1].trim(); quantity = suffix[2] || suffix[3]; unit = suffix[4]; }
  const range = quantity?.split(/\s*[-–]\s*/u);
  const amount = quantity && range.length === 1 ? numeric(quantity) : null;
  return { name, menge: Number.isFinite(amount) ? amount : null, einheit: unit ? UNITS[unit.toLowerCase()] : null,
    menge_text: range?.length === 2 ? range.join('–') : null, notiz: notes.join('; ') || null };
}

export function splitMehrfach(text) {
  const parts = [];
  let start = 0, depth = 0;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '(') depth++;
    if (text[i] === ')') depth = Math.max(0, depth - 1);
    if (!depth && ('\n\r;'.includes(text[i]) || (text[i] === ',' && !(/\d/u.test(text[i - 1] || '') && /\d/u.test(text[i + 1] || ''))))) {
      parts.push(text.slice(start, i)); start = i + 1;
    }
  }
  parts.push(text.slice(start));
  return parts.map(part => part.trim().replace(/^(?:(?:[•*☐-]|\[\s*\]|\d+\.(?=\s|$))\s*)+/u, '').trim()).filter(Boolean);
}
