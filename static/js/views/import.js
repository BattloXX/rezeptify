import { api, apiFetch } from '../api.js';
import { toast, x } from '../utils.js';
import { S } from '../app.js';
import { loadGrid, loadTags } from './home.js';
import { openNewForm } from './form.js';
import { showView } from '../app.js';

export function initImport() {
  window.switchTab     = switchTab;
  window.doUrlAnalyse  = doUrlAnalyse;
  window.doFileAnalyse = doFileAnalyse;
  window.doDragOver    = (e) => { e.preventDefault(); document.getElementById('dropzone')?.classList.add('drag'); };
  window.doDragLeave   = ()  => document.getElementById('dropzone')?.classList.remove('drag');
  window.doDrop        = (e) => { e.preventDefault(); document.getElementById('dropzone')?.classList.remove('drag'); const f = e.dataTransfer.files[0]; if (f) setImportFile(f); };
  window.fileSelected  = (e) => { if (e.target.files[0]) setImportFile(e.target.files[0]); };
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
  S.importFile = f;
  const isPdf    = f.name.toLowerCase().endsWith('.pdf');
  const preview  = document.getElementById('dz-preview');
  const imgEl    = document.getElementById('dz-img');
  const pdfEl    = document.getElementById('dz-pdf');
  const nameEl   = document.getElementById('dz-name');
  if (!preview) return;
  preview.style.display = 'block';
  if (isPdf) {
    if (imgEl) imgEl.style.display = 'none';
    if (pdfEl) pdfEl.style.display = 'block';
    if (nameEl) nameEl.textContent = f.name;
  } else {
    if (imgEl) { imgEl.src = URL.createObjectURL(f); imgEl.style.display = 'block'; }
    if (pdfEl) pdfEl.style.display = 'none';
    if (nameEl) nameEl.textContent = '';
  }
  const btn = document.getElementById('btn-file');
  if (btn) btn.disabled = false;
}

async function doUrlAnalyse() {
  const url = document.getElementById('import-url')?.value.trim();
  if (!url) { toast('Bitte URL eingeben', 'err'); return; }
  const btn = document.getElementById('btn-url');
  if (btn) btn.disabled = true;
  showLoading(true);
  try {
    const d = await api('/api/analysiere-url', { method:'POST', body: JSON.stringify({url}) });
    S.importData = d;
    renderPreview(d);
  } catch(e) { toast(e.message, 'err'); }
  finally { showLoading(false); if (btn) btn.disabled = false; }
}

async function doFileAnalyse() {
  if (!S.importFile) return;
  const btn = document.getElementById('btn-file');
  if (btn) btn.disabled = true;
  showLoading(true);
  const fd = new FormData();
  fd.append('file', S.importFile);
  try {
    const d = await apiFetch('/api/analysiere-bild', { method:'POST', body: fd });
    S.importData = d;
    renderPreview(d);
  } catch(e) { toast(e.message, 'err'); }
  finally { showLoading(false); if (btn) btn.disabled = false; }
}

function renderPreview(r) {
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
    const r = await api('/api/rezepte', { method:'POST', body: JSON.stringify(S.importData) });
    if (S.importData.downloaded_image) {
      await api('/api/rezepte/'+r.id+'/bilder/attach', {
        method:'POST', body: JSON.stringify({ dateiname: S.importData.downloaded_image, ist_haupt: true })
      }).catch(()=>{});
    }
    if (S.importData.import_image) {
      await api('/api/rezepte/'+r.id+'/bilder/attach', {
        method:'POST', body: JSON.stringify({ dateiname: S.importData.import_image, ist_haupt: false })
      }).catch(()=>{});
    }
    if (S.importFile && !('import_image' in S.importData) && !S.importFile.name.toLowerCase().endsWith('.pdf')) {
      const fd = new FormData();
      fd.append('file', S.importFile);
      fd.append('ist_haupt', (!S.importData.downloaded_image).toString());
      await apiFetch('/api/rezepte/'+r.id+'/bilder', { method:'POST', body: fd }).catch(()=>{});
    }
    toast('Rezept gespeichert ✓', 'ok');
    apiFetch('/api/rezepte/'+r.id+'/fetch-bild', { method:'POST' })
      .then(d => { if (!d.skipped) { loadGrid(); toast('🖼️ Bild hinzugefügt', 'ok'); } })
      .catch(()=>{});
    clearPreview();
    const ui = document.getElementById('import-url');
    if (ui) ui.value = '';
    resetDropzone();
    loadGrid(); loadTags();
    showView('home');
  } catch(e) { toast('Fehler: ' + e.message, 'err'); }
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
  S.importFile = null;
  const dzp = document.getElementById('dz-preview');
  if (dzp) dzp.style.display = 'none';
  const bf = document.getElementById('btn-file');
  if (bf) bf.disabled = true;
  const fi = document.getElementById('file-inp');
  if (fi) fi.value = '';
}

function showLoading(on) {
  document.getElementById('loading-box')?.classList.toggle('on', on);
  if (on) document.getElementById('preview-card')?.classList.remove('on');
}
