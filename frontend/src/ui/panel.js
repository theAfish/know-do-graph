import { api } from '../api.js';
import { escAttr, escHtml } from '../utils.js';
import { state, on, emit, EVENTS } from '../state.js';
import { highlightNode, clearHighlight, panZoomToNode } from '../graph/render.js';

export function initPanel() {
  const closeBtn = document.getElementById('detail-close');
  closeBtn?.addEventListener('click', closeDetail);

  on(EVENTS.NODE_SELECTED, openDetail);
  on(EVENTS.NODE_CLEARED, closeDetail);

  // Expose for inline onclick handlers in injected HTML.
  window.kdgFocusNode = (id) => emit(EVENTS.NODE_SELECTED, id);
  window.kdgFocusNodeBySlug = (slug) => {
    const n = state.allNodes.find((x) => x.slug === slug);
    if (n) emit(EVENTS.NODE_SELECTED, n.id);
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
  clearHighlight();
}

function renderDetailHtml(entry, nodeId) {
  const md = entry.metadata || {};
  let html = '';

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

  if (entry.scripts && entry.scripts.length) {
    const cards = entry.scripts.map((s) => {
      const reqs = s.requirements && s.requirements.length ? s.requirements.join(', ') : '—';
      const dlUrl = api.scriptDownloadUrl(entry.id, s.filename);
      return `<div class="script-card">
        ${kv('Filename', s.filename)}
        ${kv('Language', s.language || 'unknown')}
        ${kv('Requirements', reqs)}
        ${s.description ? kv('Description', s.description) : ''}
        <a class="dl-btn" href="${escAttr(dlUrl)}" download="${escAttr(s.filename)}">
          ↓ Download ${escHtml(s.filename)}
        </a>
      </div>`;
    });
    html += `<div class="detail-section">
      <div class="detail-section-title">Scripts (${entry.scripts.length})</div>
      ${cards.join('')}
    </div>`;
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
