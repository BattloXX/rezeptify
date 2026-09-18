import { api, apiFetch } from '../api.js';
import { toast, x } from '../utils.js';
import { S } from '../app.js';
import { loadGrid, loadTags } from './home.js';
import { openNewForm } from './form.js';
import { showView } from '../app.js';

let importFiles = [];
let isImportProcessing = false;

export function initImport() {
  window.switchTab     = switchTab;
  window.doUrlAnalyse  = doUrlAnalyse;
  window.doFileAnalyse = doFileAnalyse;
  window.doDragOver    = (e) => { e.preventDefault(); document.getElementById('dropzone')?.classList.add('drag'); };
  window.doDragLeave   = ()  => document.getElementById('dropzone')?.classList.remove('drag');
  window.doDrop        = (e) => { e.preventDefault(); document.getElementById('dropzone')?.classList.remove('drag'); setImportFiles(Array.from(e.dataTransfer.files || [])); };
  window.fileSelected  = (e) => setImportFiles(Array.from(e.target.files || []));
  window.doImportSave  = doImportSave;
  window.doImportEdit  = doImportEdit;
  window.clearPreview  = clearPreview;
}

function switchTab(name) {
  ['url','file'].forEach(t => {
    document.getElementById('tab-'+t)?.classList.toggle('on', t===name);
    document.getElementById('panel-'+t)?.classList.toggle('on', t===name);
  });
  clearPreview();
}

export function setImportFile(f) {
  setImportFiles(f ? [f] : []);
}

function setImportFiles(files) {
  importFiles = files;
  const f = files[0];
  S.importFile = f || null;
  if (!f) return;
  const isPdf    = f.name.toLowerCase().endsWith('.pdf');
  const isJson   = f.name.toLowerCase().endsWith('.json');
  const preview  = document.getElementById('dz-preview');
  const imgEl    = document.getElementById('dz-img');
  const pdfEl    = document.getElementById('dz-pdf');
  const nameEl   = document.getElementById('dz-name');
  if (!preview) return;
  preview.style.display = 'block';
  if (isPdf || isJson) {
    if (imgEl) imgEl.style.display = 'none';
    if (pdfEl) pdfEl.style.display = 'block';
    if (nameEl) nameEl.textContent = files.length > 1 ? `${f.name} (+${files.length - 1})` : f.name;
  } else {
    if (imgEl) { imgEl.src = URL.createObjectURL(f); imgEl.style.display = 'block'; }
    if (pdfEl) pdfEl.style.display = 'none';
    if (nameEl) nameEl.textContent = files.length > 1 ? `${files.length} Dateien ausgewählt` : '';
  }
  const btn = document.getElementById('btn-file');
  if (btn) btn.disabled = false;
  const label = document.getElementById('btn-file-label');
  const icon = document.getElementById('btn-file-icon');
  if (label) label.textContent = files.length > 1 ? `${files.length} Dateien importieren` : (isJson ? 'Rezeptdatei prüfen' : 'Mit KI analysieren');
  if (icon) icon.textContent = isJson ? 'fact_check' : 'auto_awesome';
}

async function doUrlAnalyse() {
  if (isImportProcessing) return;
  const urls = (document.getElementById('import-url')?.value || '').split(/\r?\n/).map(url => url.trim()).filter(Boolean);
  if (!urls.length) { toast('Bitte URL eingeben', 'err'); return; }
  if (urls.length > 1) return doBatchImport(urls.map(url => ({ type: 'url', value: url, label: url })));
  clearBatchResults();
  const btn = document.getElementById('btn-url');
  if (btn) btn.disabled = true;
  isImportProcessing = true;
  showLoading(true);
  try {
    const d = await analyseUrl(urls[0]);
    S.importData = d;
    renderPreview(d);
  } catch(e) { toast(e.message, 'err'); }
  finally { showLoading(false); if (btn) btn.disabled = false; isImportProcessing = false; }
}

async function doFileAnalyse() {
  if (isImportProcessing) return;
  if (!importFiles.length && S.importFile) importFiles = [S.importFile];
  if (!importFiles.length) return;
  if (importFiles.length > 1) return doBatchImport(importFiles.map(file => ({ type: 'file', value: file, label: file.name })));
  clearBatchResults();
  const btn = document.getElementById('btn-file');
  if (btn) btn.disabled = true;
  isImportProcessing = true;
  const file = importFiles[0];
  const isJson = file.name.toLowerCase().endsWith('.json');
  showLoading(true, isJson ? 'Rezeptdatei wird geprüft…' : 'KI analysiert Rezept…');
  try {
    const d = await analyseFile(file);
    S.importData = d;
    renderPreview(d);
  } catch(e) { toast(e.message, 'err'); }
  finally { showLoading(false); if (btn) btn.disabled = false; isImportProcessing = false; }
}

function renderPreview(r) {
  const previewHeader = document.querySelector('#preview-card .preview-hdr');
  if (previewHeader) previewHeader.innerHTML = r.structured_import
    ? '<span class="material-symbols-outlined">fact_check</span> Dateivorschau'
    : '<span class="material-symbols-outlined">auto_awesome</span> Vorschau';
  const gz = (r.zeit_vorb||0) + (r.zeit_koch||0);
  const previewImg = r.downloaded_image
    ? `<img class="preview-img" src="/static/uploads/${x(r.downloaded_image)}" alt="${x(r.titel)}" onerror="this.remove()">` : '';
  const allZ = r.zutaten||[];
  const realZ = allZ.filter(z => !z.gruppe);
  let shown = 0;
  const items = [];
  for (const z of allZ) {
    if (shown >= 5) break;
    if (z.gruppe) {
      items.push(`<li style="padding:5px 0 2px;font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.4px;color:var(--accent);border-bottom:none">${x(z.gruppe)}</li>`);
    } else {
      items.push(`<li style="padding:5px 0;font-size:0.86rem;border-bottom:1px solid var(--n-100)"><strong style="color:var(--accent)">${x(z.menge||'')} ${x(z.einheit||'')}</strong> ${x(z.name)}</li>`);
      shown++;
    }
  }
  const more = realZ.length > 5 ? `<li style="color:var(--muted);font-size:0.8rem;padding:4px 0">… und ${realZ.length-5} weitere</li>` : '';
  const pb = document.getElementById('preview-body');
  if (!pb) return;
  pb.innerHTML = `
    ${previewImg}
    <div class="preview-title">${x(r.titel)}</div>
    <div class="preview-chips">
      ${r.kategorie ? `<span class="preview-chip">${x(r.kategorie)}</span>` : ''}
      ${gz ? `<span class="preview-chip">⏱ ${gz} min</span>` : ''}
      ${r.schwierigkeit ? `<span class="diff-tag ${x(r.schwierigkeit)}" style="margin:0">${x(r.schwierigkeit)}</span>` : ''}
    </div>
    ${r.beschreibung ? `<p style="font-size:0.85rem;color:var(--n-600);margin-bottom:0.75rem;line-height:1.55">${x(r.beschreibung)}</p>` : ''}
    ${items.length ? `<ul style="list-style:none">${items.join('')}${more}</ul>` : ''}
  `;
  document.getElementById('preview-card')?.classList.add('on');
}

async function doImportSave() {
  if (!S.importData) return;
  try {
    const r = await saveImportedRecipe(S.importData, S.importFile);
    toast('Rezept gespeichert ✓', 'ok');
    fetchImportedImage(r.id, true);
    clearPreview();
    const ui = document.getElementById('import-url');
    if (ui) ui.value = '';
    resetDropzone();
    loadGrid(); loadTags();
    showView('home');
  } catch(e) { toast('Fehler: ' + e.message, 'err'); }
}

async function analyseUrl(url) {
  return api('/api/analysiere-url', { method:'POST', body: JSON.stringify({ url }) });
}

async function analyseFile(file) {
  const fd = new FormData();
  fd.append('file', file);
  return apiFetch('/api/analysiere-bild', { method:'POST', body: fd });
}

async function saveImportedRecipe(data, file) {
  const r = await api('/api/rezepte', { method:'POST', body: JSON.stringify(data) });
  if (data.downloaded_image) {
    await api('/api/rezepte/'+r.id+'/bilder/attach', {
      method:'POST', body: JSON.stringify({ dateiname: data.downloaded_image, ist_haupt: true })
    });
  }
  if (data.import_image) {
    await api('/api/rezepte/'+r.id+'/bilder/attach', {
      method:'POST', body: JSON.stringify({ dateiname: data.import_image, ist_haupt: false })
    });
  }
  if (file && !('import_image' in data) && !file.name.toLowerCase().endsWith('.pdf') && !file.name.toLowerCase().endsWith('.json')) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('ist_haupt', (!data.downloaded_image).toString());
    await apiFetch('/api/rezepte/'+r.id+'/bilder', { method:'POST', body: fd });
  }
  return r;
}

async function fetchImportedImage(recipeId, notify = false) {
  try {
    const result = await apiFetch('/api/rezepte/'+recipeId+'/fetch-bild', { method:'POST' });
    if (notify && !result.skipped) { loadGrid(); toast('🖼️ Bild hinzugefügt', 'ok'); }
  } catch (_) { /* optional image fetch */ }
}

async function doBatchImport(items) {
  if (isImportProcessing) return;
  isImportProcessing = true;
  const btn = document.getElementById(items[0].type === 'url' ? 'btn-url' : 'btn-file');
  if (btn) btn.disabled = true;
  clearPreview();
  renderBatchResults(items);
  let saved = 0;
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    updateBatchResult(i, 'analyzing', 'Wird analysiert/importiert …');
    showLoading(true, `${i + 1} von ${items.length}: ${item.type === 'url' ? 'KI analysiert Rezept…' : 'Rezept wird importiert…'}`);
    try {
      const data = item.type === 'url' ? await analyseUrl(item.value) : await analyseFile(item.value);
      updateBatchResult(i, 'analyzing', 'Wird gespeichert …');
      const recipe = await saveImportedRecipe(data, item.type === 'file' ? item.value : null);
      await fetchImportedImage(recipe.id);
      saved++;
      updateBatchResult(i, 'saved', 'Gespeichert ✓');
    } catch (e) {
      updateBatchResult(i, 'error', `Fehler: ${e.message || 'Unbekannter Fehler'}`);
    }
  }
  showLoading(false);
  if (btn) btn.disabled = false;
  isImportProcessing = false;
  toast(`${saved} von ${items.length} Rezepten importiert`, saved === items.length ? 'ok' : 'err');
  if (items[0].type === 'url') {
    const input = document.getElementById('import-url');
    if (input) input.value = '';
  } else {
    resetDropzone();
  }
  loadGrid(); loadTags();
}

function renderBatchResults(items) {
  const box = document.getElementById('batch-results');
  if (!box) return;
  box.innerHTML = `<div class="batch-results-hdr">Importfortschritt (${items.length} Rezepte)</div>${items.map((item, i) =>
    `<div class="batch-result" data-batch-index="${i}"><span class="batch-result-icon">○</span><div class="batch-result-text">${x(item.label)}<span class="batch-result-status">Wartend</span></div></div>`).join('')}`;
  box.classList.add('on');
}

function updateBatchResult(index, state, message) {
  const row = document.querySelector(`[data-batch-index="${index}"]`);
  if (!row) return;
  row.className = `batch-result ${state}`;
  const icon = row.querySelector('.batch-result-icon');
  if (icon) icon.textContent = state === 'saved' ? '✓' : state === 'error' ? '✗' : '◌';
  const status = row.querySelector('.batch-result-status');
  if (status) status.textContent = message;
}

function clearBatchResults() {
  const box = document.getElementById('batch-results');
  if (!box) return;
  box.classList.remove('on');
  box.innerHTML = '';
}

function doImportEdit() {
  if (!S.importData) return;
  const data = S.importData;
  clearPreview();
  openNewForm(data);
}

export function clearPreview() {
  S.importData = null;
  document.getElementById('preview-card')?.classList.remove('on');
  document.getElementById('loading-box')?.classList.remove('on');
}

function resetDropzone() {
  importFiles = [];
  S.importFile = null;
  const dzp = document.getElementById('dz-preview');
  if (dzp) dzp.style.display = 'none';
  const bf = document.getElementById('btn-file');
  if (bf) bf.disabled = true;
  const fi = document.getElementById('file-inp');
  if (fi) fi.value = '';
  const label = document.getElementById('btn-file-label');
  const icon = document.getElementById('btn-file-icon');
  if (label) label.textContent = 'Mit KI analysieren';
  if (icon) icon.textContent = 'auto_awesome';
}

function showLoading(on, message = 'KI analysiert Rezept…') {
  document.getElementById('loading-box')?.classList.toggle('on', on);
  const text = document.querySelector('#loading-box p');
  if (text) text.textContent = message;
  if (on) document.getElementById('preview-card')?.classList.remove('on');
}
