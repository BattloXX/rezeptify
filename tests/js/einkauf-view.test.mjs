import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { webcrypto } from 'node:crypto';

if (!globalThis.crypto) globalThis.crypto = webcrypto;
const url = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const read = name => readFile(new URL('../../static/js/' + name, import.meta.url), 'utf8');
const coreUrl = url(await read('einkauf-core.js'));
const parserUrl = url(await read('mengen-parser.js'));
const { createStore } = await import(url((await read('einkauf-store.js')).replace("'./einkauf-core.js'", JSON.stringify(coreUrl))));
const viewSource = await read('views/einkauf.js');
let instance = 0;

class Element {
  constructor() {
    this.listeners = {}; this.dataset = {}; this.value = ''; this.innerHTML = ''; this.hidden = false;
    this.style = {}; this.classes = new Set();
    this.classList = { add: (...names) => names.forEach(n => this.classes.add(n)), remove: (...names) => names.forEach(n => this.classes.delete(n)),
      contains: name => this.classes.has(name), toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name) };
  }
  get value() { return this._value; }
  set value(value) { this._value = String(value); }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  fire(name, event = {}) {
    event.target ||= this; event.preventDefault ||= () => {}; event.stopPropagation ||= () => {}; event.stopImmediatePropagation ||= () => {};
    for (const fn of this.listeners[name] || []) fn(event);
  }
  closest(selector) { return selector === 'button' ? this : null; }
  setAttribute() {}
  focus() {}
  after(element) { this.afterElement = element; }
}

async function setup(t, speech = false) {
  const ids = ['einkauf-liste', 'einkauf-start', 'einkauf-exit', 'einkauf-progress', 'einkauf-progress-label', 'einkauf-progress-bar', 'einkauf-finish', 'einkauf-success', 'einkauf-success-finish', 'einkauf-cart-toggle', 'einkauf-done-title', 'einkauf-autocomplete', 'einkauf-add', 'einkauf-name', 'einkauf-preview', 'einkauf-open', 'einkauf-done', 'einkauf-clean', 'einkauf-status', 'ov-einkauf-edit', 'einkauf-edit',
    ...['name', 'amount', 'unit', 'text', 'note', 'category'].map(key => 'einkauf-edit-' + key)];
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  const timers = [], messages = [];
  t.mock.method(globalThis, 'setTimeout', fn => { timers.push(fn); return timers.length; });
  t.mock.method(globalThis, 'clearTimeout', () => {});
  const doc = { listeners:{}, fire:Element.prototype.fire, body:new Element(), getElementById: id => elements[id], querySelectorAll: () => [], createElement: () => new Element(),
    addEventListener:Element.prototype.addEventListener, removeEventListener() {} };
  const recognition = [];
  class Recognition { constructor() { recognition.push(this); } start() {} }
  for (const [key, value] of Object.entries({ document:doc, window:{ listeners:{}, fire:Element.prototype.fire, location:{ href:'http://test/' }, addEventListener:Element.prototype.addEventListener, removeEventListener() {}, ...(speech ? { SpeechRecognition:Recognition } : {}) }, navigator:{ onLine:false }, history:{ state:null, pushState(state) { this.state = state; }, back() {} } })) {
    const original = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { configurable:true, value });
    t.after(() => original ? Object.defineProperty(globalThis, key, original) : delete globalThis[key]);
  }
  let snapshot;
  const store = createStore({ storage:{ load:async () => ({ artikel:[{ anzeigename:'Milch', letzte_menge:2, letzte_einheit:'l', anzahl_gekauft:5 }] }), save:async data => { snapshot = data; } } });
  await store.init();
  t.after(() => store.dispose());
  globalThis.__p3ViewStore = store;
  globalThis.__p3ViewMessages = messages;
  const storeUrl = url(`export default globalThis.__p3ViewStore; // ${++instance}`);
  const utilsUrl = url(`export const toast = (...args) => globalThis.__p3ViewMessages.push(args);
    export const toastAction = (text, label, undo) => globalThis.__p3ViewMessages.push({ text, undo });
    export const shareText = async () => {}; export const x = s => String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');`);
  const view = await import(url(viewSource.replace("'../einkauf-store.js'", JSON.stringify(storeUrl))
    .replace("'../einkauf-core.js'", JSON.stringify(coreUrl)).replace("'../mengen-parser.js'", JSON.stringify(parserUrl))
    .replace("'../utils.js'", JSON.stringify(utilsUrl)).replace("'./detail.js'", JSON.stringify(url('export const openDetail = () => {};')))));
  view.initEinkauf();
  await view.loadEinkauf();
  const click = (id, dataset) => { const button = new Element(); button.dataset = dataset; elements[id].fire('click', { target:button }); };
  return { store, elements, messages, timers, recognition, click, view, snapshot:async () => { await store.dispose(); return snapshot; } };
}

test('input preview, parsed submission, merged quantities and batch undo', async t => {
  const { store, elements:e, messages } = await setup(t);
  e['einkauf-name'].value = '2 kg Kartoffeln (Bio)'; e['einkauf-name'].fire('input');
  assert.equal(e['einkauf-preview'].textContent, '2 kg · Kartoffeln · Bio');
  e['einkauf-add'].fire('submit');
  assert.equal(store.entries()[0].menge, 2); assert.equal(store.entries()[0].notiz, 'Bio');
  e['einkauf-name'].value = '500 g Kartoffeln'; e['einkauf-add'].fire('submit');
  assert.equal(store.entries()[0].menge, 2.5);
  assert.equal(messages.at(-1).text, 'Kartoffeln: jetzt 2,5 kg');
  messages.at(-1).undo(); assert.equal(store.entries()[0].menge, 2);
  e['einkauf-name'].fire('paste', { clipboardData:{ getData:() => '• 500 g Kartoffeln\nBrot\nBrot' } });
  assert.equal(messages.at(-1).text, '3 Einträge hinzugefügt');
  assert.equal(store.entries().length, 2);
  messages.at(-1).undo();
  assert.equal(store.entries().length, 1); assert.equal(store.entries()[0].menge, 2);
});

test('editor saves only changed fields and rendered controls escape user content', async t => {
  const { store, elements:e, click, snapshot } = await setup(t);
  const id = store.add('<Brot>', { menge:1, notiz:'<Bio>' });
  assert.match(e['einkauf-open'].innerHTML, /&lt;Brot>/);
  assert.match(e['einkauf-open'].innerHTML, /&lt;Bio>/);
  assert.match(e['einkauf-open'].innerHTML, /data-delta="-1"[^>]*disabled/);
  click('einkauf-open', { edit:id }); e['einkauf-edit'].fire('submit');
  assert.equal(store.status().pending, 1);
  click('einkauf-open', { edit:id }); e['einkauf-edit-note'].value = 'regional'; e['einkauf-edit'].fire('submit');
  const ops = (await snapshot()).ops;
  assert.equal(ops.length, 2); assert.deepEqual(ops[1].daten, { notiz:'regional' });
});

test('origin removal requires a second tap and removes the recipe across entries', async t => {
  const { store, elements:e, click } = await setup(t);
  for (const name of ['Mehl', 'Milch']) store.add(name, { menge:2, herkunft:[{ rezept_id:7, menge:'2' }], manuell:false });
  click('einkauf-open', { removeRecipe:'7' });
  assert.equal(store.entries().length, 2); assert.match(e['einkauf-open'].innerHTML, /Entfernen\?/);
  click('einkauf-open', { removeRecipe:'7' }); assert.equal(store.entries().length, 0);
});

test('speech availability controls microphone and results stay in the input', async t => {
  const { store, elements:e, recognition } = await setup(t, true);
  e['einkauf-name'].afterElement.fire('click');
  assert.equal(recognition[0].lang, 'de-AT');
  recognition[0].onresult({ results:[[{ transcript:'Milch und Brot' }]] });
  assert.equal(e['einkauf-name'].value, 'Milch, Brot'); assert.equal(store.entries().length, 0);
  assert.equal(e['einkauf-preview'].textContent, '2 Einträge: Milch, Brot');
});

test('swipes keep vertical scrolling free, snap below threshold and undo completed gestures', async t => {
  const { store, elements:e, messages, timers } = await setup(t);
  assert.equal(e['einkauf-name'].afterElement, undefined);
  const id = store.add('Milch');
  const wrapper = new Element(), row = new Element(), icon = new Element();
  row.dataset.id = id; row.parentElement = wrapper; row.setPointerCapture = () => {}; row.getBoundingClientRect = () => ({ width:200 });
  wrapper.querySelector = () => icon;
  const target = { closest: selector => selector === '.shopping-row' ? row : null };
  function swipe(dx, dy = 0) {
    e['einkauf-open'].fire('pointerdown', { target, pointerId:1, isPrimary:true, clientX:0, clientY:0 });
    e['einkauf-open'].fire('pointermove', { target, pointerId:1, clientX:dx, clientY:dy });
    e['einkauf-open'].fire('pointerup', { target, pointerId:1 });
  }
  swipe(15, 40); assert.equal(store.entries()[0].erledigt, false);
  swipe(50); assert.equal(store.entries()[0].erledigt, false); assert.equal(row.style.transform, '');
  swipe(90); assert.equal(store.entries()[0].erledigt, true); messages.at(-1).undo();
  assert.equal(store.entries()[0].erledigt, false);
  swipe(-90); assert.equal(store.entries().length, 0); messages.at(-1).undo();
  assert.equal(store.entries()[0].name, 'Milch');
  timers.at(-1)?.();
});


test('category editor queues the selected category and groups open entries', async t => {
  const { store, elements:e, click, snapshot } = await setup(t);
  const id = store.add('Milch');
  click('einkauf-open', { edit:id });
  e['einkauf-edit-category'].value = '7';
  e['einkauf-edit-name'].value = 'Hafermilch';
  e['einkauf-edit'].fire('submit');
  const ops = (await snapshot()).ops;
  assert.deepEqual(ops.slice(-2).map(op => op.daten), [{ name:'Hafermilch' }, { kategorie_id:7 }]);
  assert.match(e['einkauf-open'].innerHTML, /shopping-category/);
  assert.match(e['einkauf-open'].innerHTML, /Sonstiges/);
  store.setDone(id, true);
  assert.doesNotMatch(e['einkauf-open'].innerHTML, /shopping-category/);
  assert.match(e['einkauf-done'].innerHTML, /Hafermilch/);
});

test('long press moves an open entry to another category and done entries do not arm dragging', async t => {
  const { store, elements:e, timers, snapshot } = await setup(t);
  const id = store.add('Milch'), next = store.add('Brot');
  let frame;
  globalThis.requestAnimationFrame = fn => { frame = fn; return 1; };
  globalThis.cancelAnimationFrame = () => {};
  t.after(() => { delete globalThis.requestAnimationFrame; delete globalThis.cancelAnimationFrame; });
  const category = { dataset:{ category:'7' } };
  const target = { children:[], insertBefore(el, before) {
    if (el.parentElement?.children) el.parentElement.children = el.parentElement.children.filter(child => child !== el);
    el.parentElement = target;
    const index = before ? target.children.indexOf(before) : target.children.length;
    target.children.splice(index, 0, el);
  } };
  const following = { querySelector:() => ({ dataset:{ id:next } }), getBoundingClientRect:() => ({ top:100, height:50 }) };
  target.children.push(following);
  category.querySelector = () => target;
  const wrapper = new Element(), row = new Element(), ghost = new Element();
  const rect = { width:200, height:50, left:0, top:0 };
  wrapper.getBoundingClientRect = () => rect;
  wrapper.cloneNode = () => ghost;
  wrapper.before = el => {
    el.parentElement = { children:[el, wrapper] };
    el.closest = () => category;
    el.remove = () => {};
  };
  ghost.remove = () => {};
  row.dataset.id = id; row.parentElement = wrapper; row.setPointerCapture = () => {};
  row.getBoundingClientRect = () => rect;
  document.body = { append() {} };
  document.elementFromPoint = () => ({ closest:() => category });
  const hit = { closest:() => row };
  e['einkauf-open'].fire('pointerdown', { target:hit, pointerId:1, isPrimary:true, clientX:10, clientY:20 });
  timers.at(-1)();
  assert.ok(frame);
  e['einkauf-open'].fire('pointermove', { target:hit, pointerId:1, clientX:10, clientY:80 });
  e['einkauf-open'].fire('pointerup', { target:hit, pointerId:1 });
  assert.equal(store.entries().find(entry => entry.uuid === id).kategorie_id, 7);
  const ops = (await snapshot()).ops;
  assert.deepEqual(ops.slice(-2).map(op => op.typ), ['verschieben', 'inhalt_setzen']);
  store.setDone(id, true);
  const count = timers.length;
  e['einkauf-done'].fire('pointerdown', { target:hit, pointerId:2, isPrimary:true, clientX:10, clientY:20 });
  assert.equal(timers.length, count);
  e['einkauf-done'].fire('pointercancel');
});


test('autocomplete Enter uses saved quantities; typed amounts win; Escape and arrows update selection', async t => {
  const { store, elements:e } = await setup(t);
  const input = e['einkauf-name'], box = e['einkauf-autocomplete'];
  input.value = 'Mil'; input.fire('input');
  assert.equal(box.hidden, false);
  assert.match(box.innerHTML, /Milch · 2 l/);
  input.fire('keydown', { key:'Enter' });
  assert.equal(store.entries()[0].name, 'Milch');
  assert.equal(store.entries()[0].menge, 2);
  assert.equal(box.hidden, true);
  input.value = '500 ml Mil'; input.fire('input');
  input.fire('keydown', { key:'ArrowDown' });
  assert.match(box.innerHTML, /aria-selected="true"/);
  input.fire('keydown', { key:'Enter' });
  assert.equal(store.entries()[0].menge, 2.5);
  assert.equal(store.entries()[0].einheit, 'l');
  input.value = 'Mil'; input.fire('input');
  input.fire('keydown', { key:'Escape' });
  assert.equal(box.hidden, true);
});


test('shopping mode tracks progress, checks by tap, finishes with undo and releases wake lock', async t => {
  const { store, elements:e, messages, click, view } = await setup(t);
  let requested = 0, released = 0;
  navigator.wakeLock = { request:async type => {
    assert.equal(type, 'screen'); requested++;
    return { release:async () => { released++; }, addEventListener() {} };
  } };
  document.visibilityState = 'visible';
  const id = store.add('Milch'), second = store.add('Brot');
  view.startShopping();
  await Promise.resolve(); await Promise.resolve();
  assert.equal(document.body.classList.contains('shopping-mode'), true);
  assert.equal(e['einkauf-progress'].hidden, false);
  assert.equal(e['einkauf-done'].hidden, true);
  assert.equal(e['einkauf-progress-label'].textContent, '0 / 2');
  click('einkauf-open', { edit:id });
  assert.equal(store.entries().find(row => row.uuid === id).erledigt, true);
  assert.equal(e['einkauf-cart-toggle'].textContent, 'Im Wagen (1)');
  messages.at(-1).undo(); assert.equal(store.entries().filter(row => row.erledigt).length, 0);
  click('einkauf-open', { toggle:id }); click('einkauf-open', { toggle:second });
  assert.equal(e['einkauf-success'].hidden, false);
  assert.equal(e['einkauf-progress-label'].textContent, '2 / 2');
  view.finishShopping();
  await Promise.resolve();
  assert.equal(store.entries().length, 0);
  assert.equal(document.body.classList.contains('shopping-mode'), false);
  assert.equal(requested, 1); assert.equal(released, 1);
  messages.at(-1).undo(); assert.equal(store.entries().length, 2);
});


test('shopping mode handles browser back/forward and hidden tabs reacquire wake lock', async t => {
  const { view } = await setup(t);
  let requested = 0, released = 0;
  navigator.wakeLock = { request:async () => {
    requested++;
    return { release:async () => { released++; }, addEventListener() {} };
  } };
  document.visibilityState = 'visible';
  const settle = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
  view.startShopping(); await settle();
  document.visibilityState = 'hidden'; document.fire('visibilitychange'); await settle();
  assert.equal(released, 1);
  document.visibilityState = 'visible'; document.fire('visibilitychange'); await settle();
  assert.equal(requested, 2);
  window.fire('popstate', { state:null }); await settle();
  assert.equal(document.body.classList.contains('shopping-mode'), false);
  assert.equal(released, 2);
  // Forward navigation also works without a Wake Lock API.
  delete navigator.wakeLock;
  window.fire('popstate', { state:{ shoppingMode:true } });
  assert.equal(document.body.classList.contains('shopping-mode'), true);
  window.fire('popstate', { state:null });
  assert.equal(document.body.classList.contains('shopping-mode'), false);
});
