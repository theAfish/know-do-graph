import { api } from '../../api.js';
import { ENTRY_TYPES, VERIFICATION_COLORS } from '../../constants.js';
import { clearHighlight, highlightNode, panZoomToNode } from '../../graph/render.js';
import { byId, queryRequired } from '../../dom.js';
import { emit, EVENTS, on, state } from '../../state.js';
import { escAttr, escHtml } from '../../utils.js';

/** @type {import('../../types.js').GraphNode|null} */
let currentEntry = null;

export function initPanel() {
  byId('detail-close', HTMLButtonElement).addEventListener('click', closeDetail);
  byId('detail-body').addEventListener('click', handlePanelClick);
  byId('detail-body').addEventListener('submit', handleEditSubmit);

  on(EVENTS.NODE_SELECTED, (nodeId) => openDetail(String(nodeId)));
  on(EVENTS.NODE_CLEARED, closeDetail);
}

export async function openDetail(nodeId) {
  state.selectedId = nodeId;

  let entry;
  try {
    entry = await api.getEntry(nodeId);
  } catch {
    entry = state.allNodes.find((n) => n.id === nodeId);
  }
  if (!entry || state.selectedId !== nodeId) return;
  currentEntry = entry;

  const panel = byId('detail');
  const body = byId('detail-body');
  byId('detail-title').textContent = entry.title || nodeId;

  body.innerHTML = renderDetailHtml(entry, nodeId);
  panel.classList.remove('hidden');
  panel.focus();
  highlightNode(nodeId);
  panZoomToNode(nodeId);
}

export function closeDetail() {
  byId('detail').classList.add('hidden');
  state.selectedId = null;
  currentEntry = null;
  clearHighlight();
}

/**
 * @param {import('../../types.js').GraphNode} entry
 * @param {string} nodeId
 */
export function renderDetailHtml(entry, nodeId) {
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

  if (entry.tags?.length) {
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
    kv('Reviewed times', md.review_count ?? 0),
  ].filter(Boolean);
  if (mdRows.length) html += section('Metadata', mdRows);

  if (md.remote_source) html += renderRemoteSourceHtml(entry.id, md.remote_source);

  if (entry.assets?.length) {
    html += renderAssetsHtml(entry);
  } else if (entry.scripts?.length) {
    html += renderLegacyScriptsHtml(entry);
  }

  if (md.related_environments?.length) {
    html += section('Related environments', [kv('', md.related_environments.join(', '))]);
  }
  if (md.runtime_requirements?.length) {
    html += section('Runtime requirements', [kv('', md.runtime_requirements.join(', '))]);
  }
  if (md.external_refs?.length) {
    html += section('External refs', [kv('', md.external_refs.join(', '))]);
  }

  if (entry.internal_refs?.length) {
    html += `<div class="detail-section">
      <div class="detail-section-title">Wikilinks (${entry.internal_refs.length})</div>
      ${entry.internal_refs
        .map(
          (slug) =>
            `<div class="edge-list-item">${linkButton(
              slug,
              'focus-node-slug',
              'slug',
              slug,
            )}</div>`,
        )
        .join('')}
    </div>`;
  }

  const outEdges = state.allEdges.filter((e) => (e.source.id || e.source) === nodeId);
  const inEdges = state.allEdges.filter((e) => (e.target.id || e.target) === nodeId);
  if (outEdges.length || inEdges.length) {
    html += `<div class="detail-section"><div class="detail-section-title">Connections (${outEdges.length + inEdges.length})</div>`;
    for (const e of outEdges) {
      const tid = e.target.id || e.target;
      const tnode = state.allNodes.find((n) => n.id === tid);
      html += edgeItem('->', e.relation, tid, tnode);
    }
    for (const e of inEdges) {
      const sid = e.source.id || e.source;
      const snode = state.allNodes.find((n) => n.id === sid);
      html += edgeItem('<-', e.relation, sid, snode);
    }
    html += '</div>';
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
  const trigger = event.target instanceof Element ? event.target.closest('[data-action]') : null;
  const action = trigger?.dataset.action;
  if (!action) return;

  if (action === 'focus-node') {
    emit(EVENTS.NODE_SELECTED, trigger.dataset.id);
    return;
  }
  if (action === 'focus-node-slug') {
    const node = state.allNodes.find((item) => item.slug === trigger.dataset.slug);
    if (node) emit(EVENTS.NODE_SELECTED, node.id);
    return;
  }
  if (action === 'sync-remote') {
    syncRemote(trigger);
    return;
  }
  if (!currentEntry) return;

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
  byId('detail-title').textContent = currentEntry.title || state.selectedId;
  byId('detail-body').innerHTML = renderDetailHtml(currentEntry, state.selectedId);
}

function renderEditForm(entry) {
  const typeOptions = ENTRY_TYPES.map(
    (type) =>
      `<option value="${escAttr(type)}"${type === entry.entry_type ? ' selected' : ''}>${escHtml(type)}</option>`,
  ).join('');
  const verificationOptions = Object.keys(VERIFICATION_COLORS)
    .map(
      (status) =>
        `<option value="${escAttr(status)}"${status === entry.metadata?.verification_status ? ' selected' : ''}>${escHtml(status)}</option>`,
    )
    .join('');

  byId('detail-title').textContent = `Edit ${entry.title}`;
  byId('detail-body').innerHTML = `
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
        <span>Verification</span>
        <select name="verification_status">${verificationOptions}</select>
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
  queryRequired(byId('detail-body'), 'input[name="title"]', HTMLInputElement).focus();
}

async function handleEditSubmit(event) {
  if (!(event.target instanceof HTMLFormElement) || event.target.id !== 'node-edit-form') return;
  if (!currentEntry) return;
  event.preventDefault();

  const form = event.target;
  const submitBtn = queryRequired(form, 'button[type="submit"]', HTMLButtonElement);
  const errorEl = byId('node-edit-error');
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
    metadata: {
      ...(currentEntry.metadata || {}),
      verification_status: String(data.get('verification_status') || 'unverified'),
    },
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

  const deleteBtn = queryRequired(
    byId('detail-body'),
    '[data-action="delete-node"]',
    HTMLButtonElement,
  );
  deleteBtn.disabled = true;
  deleteBtn.textContent = 'Deleting...';
  try {
    await api.deleteEntry(entry.id);
    closeDetail();
    emit(EVENTS.GRAPH_REFRESH);
  } catch (error) {
    deleteBtn.disabled = false;
    deleteBtn.textContent = 'Delete';
    showPanelError(`Could not delete node: ${error.message}`);
  }
}

async function syncRemote(trigger) {
  const entryId = trigger.dataset.entryId;
  if (!entryId) return;
  trigger.disabled = true;
  trigger.textContent = 'Syncing...';
  try {
    const res = await api.syncRemote(entryId, { force: true });
    await openDetail(entryId);
    const status = res?.result?.status || 'done';
    trigger.textContent = `Sync now (last: ${status})`;
  } catch (error) {
    trigger.textContent = `Sync failed: ${error.message}`;
  } finally {
    trigger.disabled = false;
  }
}

function showPanelError(message) {
  const body = byId('detail-body');
  const existing = body.querySelector('.panel-error');
  if (existing) {
    existing.textContent = message;
    return;
  }
  body.insertAdjacentHTML(
    'afterbegin',
    `<div class="panel-error" role="alert">${escHtml(message)}</div>`,
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

function linkButton(label, action, dataName, dataValue) {
  return `<button class="node-link" type="button" data-action="${escAttr(action)}" data-${escAttr(dataName)}="${escAttr(dataValue)}">${escHtml(label)}</button>`;
}

function edgeItem(arrow, relation, id, node) {
  const label = node ? node.title : id;
  return `<div class="edge-list-item">
    <span class="dir-badge">${arrow}</span>
    <span class="rel-badge">${escHtml(relation || 'link')}</span>
    ${linkButton(label, 'focus-node', 'id', id)}
  </div>`;
}

const FOLDER_ORDER = ['scripts', 'references', 'docs', 'examples', 'data', 'notes'];
const FOLDER_ICONS = {
  scripts: 'code',
  references: 'link',
  docs: 'doc',
  examples: 'ex',
  data: 'data',
  notes: 'note',
};

function renderRemoteSourceHtml(entryId, src) {
  const statusColor =
    {
      ok: '#2e8b57',
      stale: '#c98306',
      error: '#c0392b',
      never: '#888',
    }[src.status] || '#888';
  const fetched = src.fetched_at ? new Date(src.fetched_at).toLocaleString() : '-';
  const linkHtml = `<a href="${escAttr(src.url)}" target="_blank" rel="noopener">${escHtml(src.url)}</a>`;
  const ghLine =
    src.kind === 'github'
      ? `<div class="detail-kv"><span class="k">GitHub</span><span class="v">${escHtml(src.owner || '?')}/${escHtml(src.repo || '?')} @ <code>${escHtml(src.ref || 'main')}</code></span></div>
       <div class="detail-kv"><span class="k">Path</span><span class="v"><code>${escHtml(src.path || '')}</code></span></div>`
      : '';
  const errLine = src.last_error
    ? `<div class="detail-kv"><span class="k">Last error</span><span class="v remote-error">${escHtml(src.last_error)}</span></div>`
    : '';
  return `<div class="detail-section">
    <div class="detail-section-title">
      Remote source
      <span class="remote-status" style="background:${statusColor}">${escHtml(src.status || 'never')}</span>
    </div>
    <div class="detail-kv"><span class="k">URL</span><span class="v">${linkHtml}</span></div>
    ${ghLine}
    <div class="detail-kv"><span class="k">Last fetched</span><span class="v">${escHtml(fetched)}</span></div>
    <div class="detail-kv"><span class="k">Auto-sync</span><span class="v">${src.auto_sync ? `every ${src.sync_interval_seconds}s` : 'off'}</span></div>
    ${errLine}
    <div class="remote-actions">
      <button class="tag-pill button-pill" type="button" data-action="sync-remote" data-entry-id="${escAttr(entryId)}">Sync now</button>
    </div>
  </div>`;
}

function groupAssetsByFolder(assets) {
  const groups = {};
  for (const asset of assets) {
    const folder = asset.folder || 'notes';
    (groups[folder] ||= []).push(asset);
  }
  const ordered = {};
  for (const folder of FOLDER_ORDER) if (groups[folder]) ordered[folder] = groups[folder];
  for (const folder of Object.keys(groups).sort()) {
    if (!(folder in ordered)) ordered[folder] = groups[folder];
  }
  return ordered;
}

function renderAssetsHtml(entry) {
  const grouped = groupAssetsByFolder(entry.assets);
  const folders = Object.keys(grouped);
  if (!folders.length) return '';

  const blocks = folders.map((folder, idx) => {
    const items = grouped[folder];
    const open = idx === 0 ? ' open' : '';
    const icon = FOLDER_ICONS[folder] || 'file';
    const itemsHtml = items.map((asset) => renderAssetItem(entry.id, asset)).join('');
    return `<details class="asset-folder"${open}>
      <summary class="asset-folder-summary">
        <span class="asset-folder-icon">${escHtml(icon)}</span>
        <span class="asset-folder-name">${escHtml(folder)}</span>
        <span class="asset-folder-count">${items.length}</span>
      </summary>
      <div class="asset-folder-body">${itemsHtml}</div>
    </details>`;
  });

  return `<div class="detail-section">
    <div class="detail-section-title">Assets (${entry.assets.length})</div>
    <div class="asset-tree">${blocks.join('')}</div>
  </div>`;
}

function renderAssetItem(entryId, asset) {
  const url = api.assetUrl(entryId, asset.folder, asset.filename);
  const reqs = asset.requirements?.length ? asset.requirements.join(', ') : '';
  const lang = asset.language ? `<span class="asset-tag">${escHtml(asset.language)}</span>` : '';
  const kind = `<span class="asset-tag asset-kind-${escAttr(asset.kind || 'file')}">${escHtml(asset.kind || 'file')}</span>`;
  const sizeKb = typeof asset.size === 'number' ? `${(asset.size / 1024).toFixed(1)} KB` : '';
  const desc = asset.description
    ? `<div class="asset-desc">${escHtml(asset.description)}</div>`
    : '';
  const reqsRow = reqs
    ? `<div class="asset-meta-row"><span class="k">requires</span><span class="v">${escHtml(reqs)}</span></div>`
    : '';
  const sizeRow = sizeKb
    ? `<div class="asset-meta-row"><span class="k">size</span><span class="v">${escHtml(sizeKb)}</span></div>`
    : '';

  let action;
  if (asset.kind === 'link') {
    action = `<a class="asset-btn link" href="${escAttr(asset.download_url || url)}" target="_blank" rel="noopener">Open link</a>`;
  } else if (asset.kind === 'text') {
    action = `<a class="asset-btn" href="${escAttr(url)}" target="_blank" rel="noopener">View</a>`;
  } else {
    action = `<a class="asset-btn dl" href="${escAttr(url)}" download="${escAttr(asset.filename.split('/').pop())}">Download</a>`;
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
  const cards = entry.scripts
    .map((script) => {
      const reqs = script.requirements?.length ? script.requirements.join(', ') : '-';
      const dlUrl = api.scriptDownloadUrl(entry.id, script.filename);
      return `<div class="asset-item">
      <div class="asset-item-head">
        <span class="asset-filename">${escHtml(script.filename)}</span>
        <span class="asset-tag">${escHtml(script.language || 'unknown')}</span>
      </div>
      ${script.description ? `<div class="asset-desc">${escHtml(script.description)}</div>` : ''}
      <div class="asset-meta-row"><span class="k">requires</span><span class="v">${escHtml(reqs)}</span></div>
      <a class="asset-btn dl" href="${escAttr(dlUrl)}" download="${escAttr(script.filename)}">Download</a>
    </div>`;
    })
    .join('');
  return `<div class="detail-section">
    <div class="detail-section-title">Scripts (${entry.scripts.length})</div>
    <details class="asset-folder" open>
      <summary class="asset-folder-summary">
        <span class="asset-folder-icon">code</span>
        <span class="asset-folder-name">scripts</span>
        <span class="asset-folder-count">${entry.scripts.length}</span>
      </summary>
      <div class="asset-folder-body">${cards}</div>
    </details>
  </div>`;
}
