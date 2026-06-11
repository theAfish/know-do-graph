import { api } from '../api.js';
import { ENTRY_TYPES } from '../constants.js';
import { escAttr, escHtml } from '../utils.js';
import { state, on, emit, EVENTS } from '../state.js';
import { highlightNode, clearHighlight, panZoomToNode } from '../graph/render.js';

let currentEntry = null;

export function initPanel() {
  const closeBtn = document.getElementById('detail-close');
  closeBtn?.addEventListener('click', closeDetail);
  document.getElementById('detail-body')?.addEventListener('click', handlePanelClick);
  document.getElementById('detail-body')?.addEventListener('submit', handleEditSubmit);

  on(EVENTS.NODE_SELECTED, openDetail);
  on(EVENTS.NODE_CLEARED, closeDetail);

  // Expose for inline onclick handlers in injected HTML.
  window.kdgFocusNode = (id) => emit(EVENTS.NODE_SELECTED, id);
  window.kdgFocusNodeBySlug = (slug) => {
    const n = state.allNodes.find((x) => x.slug === slug);
    if (n) emit(EVENTS.NODE_SELECTED, n.id);
  };
  window.kdgSyncRemote = async (entryId, btnId) => {
    const btn = document.getElementById(btnId);
    if (btn) { btn.disabled = true; btn.textContent = 'Syncing…'; }
    try {
      const res = await api.syncRemote(entryId, { force: true });
      // Re-open detail to reflect freshly fetched body / new fetched_at.
      await openDetail(entryId);
      const status = res?.result?.status || 'done';
      if (btn) btn.textContent = `↻ Sync now (last: ${status})`;
    } catch (e) {
      if (btn) btn.textContent = `Sync failed: ${e.message}`;
    } finally {
      if (btn) btn.disabled = false;
    }
  };
}

export async function openDetail(nodeId) {
  state.selectedId = nodeId;

  let entry;
  try {
    entry = await api.getEntry(nodeId);
  } catch {
    entry = state.allNodes.find((n) => n.id === nodeId);
  }
  if (!entry) return;
  if (state.selectedId !== nodeId) return;
  currentEntry = entry;

  const panel = document.getElementById('detail');
  const body = document.getElementById('detail-body');
  document.getElementById('detail-title').textContent = entry.title || nodeId;

  body.innerHTML = renderDetailHtml(entry, nodeId);

  panel.classList.remove('hidden');
  highlightNode(nodeId);
  panZoomToNode(nodeId);
}

export function closeDetail() {
  document.getElementById('detail')?.classList.add('hidden');
  state.selectedId = null;
  currentEntry = null;
  clearHighlight();
}

function renderDetailHtml(entry, nodeId) {
  const md = entry.metadata || {};
  let html = `<div class="detail-actions">
    <button class="panel-btn" type="button" data-action="edit-node">Edit</button>
    <button class="panel-btn danger" type="button" data-action="delete-node">Delete</button>
  </div>`;

  html += section('Identity', [
    kv('ID', entry.id),
    kv('Slug', entry.slug),
    kv('Type', entry.entry_type),
  ]);

  if (entry.content) {
    html += `<div class="detail-section">
      <div class="detail-section-title">Content</div>
      <div class="content-block">${escHtml(entry.content)}</div>
    </div>`;
  }

  if (entry.tags && entry.tags.length) {
    html += `<div class="detail-section">
      <div class="detail-section-title">Tags</div>
      <div>${entry.tags.map((t) => `<span class="tag-pill">${escHtml(t)}</span>`).join('')}</div>
    </div>`;
  }

  const mdRows = [
    kv('Refinement status', md.refinement_status),
    kv('Trust score', md.trust_score),
    kv('Usage count', md.usage_count),
    kv('Source provenance', md.source_provenance),
    kv('Extraction method', md.extraction_method),
    kv('Verification', md.verification_status),
  ].filter(Boolean);
  if (mdRows.length) html += section('Metadata', mdRows);

  if (md.remote_source) html += renderRemoteSourceHtml(entry.id, md.remote_source);

  if (entry.assets && entry.assets.length) {
    html += renderAssetsHtml(entry);
  } else if (entry.scripts && entry.scripts.length) {
    // Backward compat: render legacy scripts even if assets list was not synced.
    html += renderLegacyScriptsHtml(entry);
  }

  if (md.related_environments && md.related_environments.length)
    html += section('Related environments', [kv('', md.related_environments.join(', '))]);
  if (md.runtime_requirements && md.runtime_requirements.length)
    html += section('Runtime requirements', [kv('', md.runtime_requirements.join(', '))]);
  if (md.external_refs && md.external_refs.length)
    html += section('External refs', [kv('', md.external_refs.join(', '))]);

  if (entry.internal_refs && entry.internal_refs.length) {
    html += `<div class="detail-section">
      <div class="detail-section-title">Wikilinks (${entry.internal_refs.length})</div>
      ${entry.internal_refs
        .map(
          (r) =>
            `<div class="edge-list-item"><span class="node-link" onclick="kdgFocusNodeBySlug('${escAttr(r)}')">${escHtml(r)}</span></div>`
        )
        .join('')}
    </div>`;
  }

  // Connections (from in-memory edges)
  const outEdges = state.allEdges.filter(
    (e) => (e.source.id || e.source) === nodeId
  );
  const inEdges = state.allEdges.filter(
    (e) => (e.target.id || e.target) === nodeId
  );
  if (outEdges.length || inEdges.length) {
    html += `<div class="detail-section"><div class="detail-section-title">Connections (${outEdges.length + inEdges.length})</div>`;
    for (const e of outEdges) {
      const tid = e.target.id || e.target;
      const tnode = state.allNodes.find((n) => n.id === tid);
      html += edgeItem('→', e.relation, tid, tnode);
    }
    for (const e of inEdges) {
      const sid = e.source.id || e.source;
      const snode = state.allNodes.find((n) => n.id === sid);
      html += edgeItem('←', e.relation, sid, snode);
    }
    html += `</div>`;
  }

  if (md.custom && Object.keys(md.custom).length) {
    html += `<div class="detail-section">
      <div class="detail-section-title">Custom metadata</div>
      <pre class="content-block">${escHtml(JSON.stringify(md.custom, null, 2))}</pre>
    </div>`;
  }

  return html;
}

function handlePanelClick(event) {
  const action = event.target.closest('[data-action]')?.dataset.action;
  if (!action || !currentEntry) return;

  if (action === 'edit-node') {
    renderEditForm(currentEntry);
  } else if (action === 'cancel-edit') {
    renderCurrentDetail();
  } else if (action === 'delete-node') {
    deleteCurrentNode();
  }
}

function renderCurrentDetail() {
  if (!currentEntry || !state.selectedId) return;
  document.getElementById('detail-title').textContent = currentEntry.title || state.selectedId;
  document.getElementById('detail-body').innerHTML =
    renderDetailHtml(currentEntry, state.selectedId);
}

function renderEditForm(entry) {
  const typeOptions = ENTRY_TYPES.map(
    (type) =>
      `<option value="${escAttr(type)}"${type === entry.entry_type ? ' selected' : ''}>${escHtml(type)}</option>`
  ).join('');

  document.getElementById('detail-title').textContent = `Edit ${entry.title}`;
  document.getElementById('detail-body').innerHTML = `
    <form id="node-edit-form" class="node-edit-form">
      <label>
        <span>Title</span>
        <input name="title" value="${escAttr(entry.title || '')}" required />
      </label>
      <label>
        <span>Slug</span>
        <input name="slug" value="${escAttr(entry.slug || '')}" />
      </label>
      <label>
        <span>Type</span>
        <select name="entry_type">${typeOptions}</select>
      </label>
      <label>
        <span>Tags <small>comma-separated</small></span>
        <input name="tags" value="${escAttr((entry.tags || []).join(', '))}" />
      </label>
      <label>
        <span>Aliases <small>comma-separated</small></span>
        <input name="aliases" value="${escAttr((entry.aliases || []).join(', '))}" />
      </label>
      <label>
        <span>Content</span>
        <textarea name="content" rows="14">${escHtml(entry.content || '')}</textarea>
      </label>
      <div id="node-edit-error" class="form-error" role="alert" hidden></div>
      <div class="form-actions">
        <button class="panel-btn primary" type="submit">Save changes</button>
        <button class="panel-btn" type="button" data-action="cancel-edit">Cancel</button>
      </div>
    </form>`;
}

async function handleEditSubmit(event) {
  if (event.target.id !== 'node-edit-form' || !currentEntry) return;
  event.preventDefault();

  const form = event.target;
  const submitBtn = form.querySelector('button[type="submit"]');
  const errorEl = document.getElementById('node-edit-error');
  const data = new FormData(form);
  const splitList = (value) =>
    String(value || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);

  const payload = {
    ...currentEntry,
    title: String(data.get('title') || '').trim(),
    slug: String(data.get('slug') || '').trim(),
    entry_type: String(data.get('entry_type') || 'generic'),
    tags: splitList(data.get('tags')),
    aliases: splitList(data.get('aliases')),
    content: String(data.get('content') || ''),
  };

  submitBtn.disabled = true;
  submitBtn.textContent = 'Saving...';
  errorEl.hidden = true;
  try {
    currentEntry = await api.updateEntry(currentEntry.id, payload);
    renderCurrentDetail();
    emit(EVENTS.GRAPH_REFRESH);
  } catch (error) {
    errorEl.textContent = `Could not save node: ${error.message}`;
    errorEl.hidden = false;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Save changes';
  }
}

async function deleteCurrentNode() {
  if (!currentEntry) return;
  const entry = currentEntry;
  const linkCount = state.allEdges.filter((edge) => {
    const source = edge.source.id || edge.source;
    const target = edge.target.id || edge.target;
    return source === entry.id || target === entry.id;
  }).length;
  const linkText = `${linkCount} connected link${linkCount === 1 ? '' : 's'}`;
  if (!window.confirm(`Delete "${entry.title}" and ${linkText}? This cannot be undone.`)) return;

  const deleteBtn = document.querySelector('[data-action="delete-node"]');
  if (deleteBtn) {
    deleteBtn.disabled = true;
    deleteBtn.textContent = 'Deleting...';
  }
  try {
    await api.deleteEntry(entry.id);
    closeDetail();
    emit(EVENTS.GRAPH_REFRESH);
  } catch (error) {
    if (deleteBtn) {
      deleteBtn.disabled = false;
      deleteBtn.textContent = 'Delete';
    }
    showPanelError(`Could not delete node: ${error.message}`);
  }
}

function showPanelError(message) {
  const body = document.getElementById('detail-body');
  const existing = body.querySelector('.panel-error');
  if (existing) {
    existing.textContent = message;
    return;
  }
  body.insertAdjacentHTML(
    'afterbegin',
    `<div class="panel-error" role="alert">${escHtml(message)}</div>`
  );
}

function kv(key, val) {
  if (val == null || val === '') return '';
  return `<div class="detail-kv"><span class="k">${escHtml(key)}</span><span class="v">${escHtml(String(val))}</span></div>`;
}

function section(title, rows) {
  const content = rows.filter(Boolean).join('');
  if (!content) return '';
  return `<div class="detail-section"><div class="detail-section-title">${escHtml(title)}</div>${content}</div>`;
}

function edgeItem(arrow, relation, id, node) {
  const label = node ? node.title : id;
  return `<div class="edge-list-item">
    <span class="dir-badge">${arrow}</span>
    <span class="rel-badge">${escHtml(relation || 'link')}</span>
    <span class="node-link" onclick="kdgFocusNode('${escAttr(id)}')">${escHtml(label)}</span>
  </div>`;
}

// ── Assets (folder-style) ────────────────────────────────────────────────────

const FOLDER_ORDER = ['scripts', 'references', 'docs', 'examples', 'data', 'notes'];
const FOLDER_ICONS = {
  scripts: '⚙',
  references: '🔗',
  docs: '📄',
  examples: '🧪',
  data: '📊',
  notes: '📝',
};

function renderRemoteSourceHtml(entryId, src) {
  const statusColor = {
    ok: '#2e8b57',
    stale: '#c98306',
    error: '#c0392b',
    never: '#888',
  }[src.status] || '#888';
  const fetched = src.fetched_at ? new Date(src.fetched_at).toLocaleString() : '—';
  const btnId = `kdg-sync-btn-${entryId}`;
  const linkHtml = `<a href="${escAttr(src.url)}" target="_blank" rel="noopener">${escHtml(src.url)}</a>`;
  const ghLine = src.kind === 'github'
    ? `<div class="detail-kv"><span class="k">GitHub</span><span class="v">${escHtml(src.owner || '?')}/${escHtml(src.repo || '?')} @ <code>${escHtml(src.ref || 'main')}</code></span></div>
       <div class="detail-kv"><span class="k">Path</span><span class="v"><code>${escHtml(src.path || '')}</code></span></div>`
    : '';
  const errLine = src.last_error
    ? `<div class="detail-kv"><span class="k">Last error</span><span class="v" style="color:#c0392b">${escHtml(src.last_error)}</span></div>`
    : '';
  return `<div class="detail-section">
    <div class="detail-section-title">
      Remote source
      <span style="margin-left:.5em;padding:1px 6px;border-radius:8px;background:${statusColor};color:#fff;font-size:.75em;text-transform:uppercase">${escHtml(src.status || 'never')}</span>
    </div>
    <div class="detail-kv"><span class="k">URL</span><span class="v">${linkHtml}</span></div>
    ${ghLine}
    <div class="detail-kv"><span class="k">Last fetched</span><span class="v">${escHtml(fetched)}</span></div>
    <div class="detail-kv"><span class="k">Auto-sync</span><span class="v">${src.auto_sync ? `every ${src.sync_interval_seconds}s` : 'off'}</span></div>
    ${errLine}
    <div style="margin-top:.5em">
      <button id="${btnId}" class="tag-pill" style="cursor:pointer;border:none"
              onclick="kdgSyncRemote('${escAttr(entryId)}','${btnId}')">↻ Sync now</button>
    </div>
  </div>`;
}

function groupAssetsByFolder(assets) {
  const groups = {};
  for (const a of assets) {
    const f = a.folder || 'notes';
    (groups[f] ||= []).push(a);
  }
  const ordered = {};
  for (const f of FOLDER_ORDER) if (groups[f]) ordered[f] = groups[f];
  for (const f of Object.keys(groups).sort()) if (!(f in ordered)) ordered[f] = groups[f];
  return ordered;
}

function renderAssetsHtml(entry) {
  const grouped = groupAssetsByFolder(entry.assets);
  const folders = Object.keys(grouped);
  if (!folders.length) return '';

  const blocks = folders.map((folder, idx) => {
    const items = grouped[folder];
    const open = idx === 0 ? ' open' : '';
    const icon = FOLDER_ICONS[folder] || '📁';
    const itemsHtml = items.map((a) => renderAssetItem(entry.id, a)).join('');
    return `<details class="asset-folder"${open}>
      <summary class="asset-folder-summary">
        <span class="asset-folder-icon">${icon}</span>
        <span class="asset-folder-name">${escHtml(folder)}</span>
        <span class="asset-folder-count">${items.length}</span>
      </summary>
      <div class="asset-folder-body">${itemsHtml}</div>
    </details>`;
  });

  const total = entry.assets.length;
  return `<div class="detail-section">
    <div class="detail-section-title">Assets (${total})</div>
    <div class="asset-tree">${blocks.join('')}</div>
  </div>`;
}

function renderAssetItem(entryId, asset) {
  const url = api.assetUrl(entryId, asset.folder, asset.filename);
  const reqs = asset.requirements && asset.requirements.length ? asset.requirements.join(', ') : '';
  const lang = asset.language ? `<span class="asset-tag">${escHtml(asset.language)}</span>` : '';
  const kind = `<span class="asset-tag asset-kind-${escAttr(asset.kind || 'file')}">${escHtml(asset.kind || 'file')}</span>`;
  const sizeKb = typeof asset.size === 'number' ? `${(asset.size / 1024).toFixed(1)} KB` : '';
  const desc = asset.description ? `<div class="asset-desc">${escHtml(asset.description)}</div>` : '';
  const reqsRow = reqs ? `<div class="asset-meta-row"><span class="k">requires</span><span class="v">${escHtml(reqs)}</span></div>` : '';
  const sizeRow = sizeKb ? `<div class="asset-meta-row"><span class="k">size</span><span class="v">${escHtml(sizeKb)}</span></div>` : '';

  let action;
  if (asset.kind === 'link') {
    action = `<a class="asset-btn link" href="${escAttr(asset.download_url || url)}" target="_blank" rel="noopener">↗ Open link</a>`;
  } else if (asset.kind === 'text') {
    action = `<a class="asset-btn" href="${escAttr(url)}" target="_blank" rel="noopener">⤴ View</a>`;
  } else {
    action = `<a class="asset-btn dl" href="${escAttr(url)}" download="${escAttr(asset.filename.split('/').pop())}">↓ Download</a>`;
  }

  return `<div class="asset-item">
    <div class="asset-item-head">
      <span class="asset-filename" title="${escAttr(asset.filename)}">${escHtml(asset.filename)}</span>
      ${kind}${lang}
    </div>
    ${desc}
    ${reqsRow}${sizeRow}
    ${action}
  </div>`;
}

function renderLegacyScriptsHtml(entry) {
  const cards = entry.scripts.map((s) => {
    const reqs = s.requirements && s.requirements.length ? s.requirements.join(', ') : '—';
    const dlUrl = api.scriptDownloadUrl(entry.id, s.filename);
    return `<div class="asset-item">
      <div class="asset-item-head">
        <span class="asset-filename">${escHtml(s.filename)}</span>
        <span class="asset-tag">${escHtml(s.language || 'unknown')}</span>
      </div>
      ${s.description ? `<div class="asset-desc">${escHtml(s.description)}</div>` : ''}
      <div class="asset-meta-row"><span class="k">requires</span><span class="v">${escHtml(reqs)}</span></div>
      <a class="asset-btn dl" href="${escAttr(dlUrl)}" download="${escAttr(s.filename)}">↓ Download</a>
    </div>`;
  }).join('');
  return `<div class="detail-section">
    <div class="detail-section-title">Scripts (${entry.scripts.length})</div>
    <details class="asset-folder" open>
      <summary class="asset-folder-summary">
        <span class="asset-folder-icon">⚙</span>
        <span class="asset-folder-name">scripts</span>
        <span class="asset-folder-count">${entry.scripts.length}</span>
      </summary>
      <div class="asset-folder-body">${cards}</div>
    </details>
  </div>`;
}
