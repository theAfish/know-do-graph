import { ENTRY_TYPES } from '../constants.js';
import { state, on, emit, EVENTS } from '../state.js';
import { resetView, getSelections } from '../graph/render.js';

export function initToolbar() {
  populateTypeFilter();
  bindButtons();
  bindSSEStatus();
}

function populateTypeFilter() {
  const sel = document.getElementById('type-filter');
  if (!sel) return;
  for (const t of ENTRY_TYPES) {
    const opt = document.createElement('option');
    opt.value = t;
    opt.textContent = t;
    sel.appendChild(opt);
  }
}

function bindButtons() {
  const labelsBtn = document.getElementById('toggle-labels');
  const scoreBtn = document.getElementById('toggle-score');
  const resetBtn = document.getElementById('reset-view');

  syncLabelBtn(labelsBtn);
  syncScoreBtn(scoreBtn);

  labelsBtn?.addEventListener('click', () => {
    state.showLabels = !state.showLabels;
    syncLabelBtn(labelsBtn);
    const { sceneSel } = getSelections();
    sceneSel
      ?.selectAll('.node text:not(.score-label)')
      .style('display', state.showLabels ? null : 'none');
    emit(EVENTS.LABELS_CHANGED, state.showLabels);
  });

  scoreBtn?.addEventListener('click', () => {
    state.scoreMode = !state.scoreMode;
    syncScoreBtn(scoreBtn);
    emit(EVENTS.SCORE_MODE_CHANGED, state.scoreMode);
  });

  resetBtn?.addEventListener('click', () => resetView());
}

function syncLabelBtn(btn) {
  if (!btn) return;
  btn.textContent = `Labels: ${state.showLabels ? 'on' : 'off'}`;
  btn.classList.toggle('active', state.showLabels);
}

function syncScoreBtn(btn) {
  if (!btn) return;
  btn.textContent = `Relevance: ${state.scoreMode ? 'on' : 'off'}`;
  btn.classList.toggle('active', state.scoreMode);
}

function bindSSEStatus() {
  const badge = document.getElementById('live-badge');
  if (!badge) return;
  const map = {
    connected: { cls: 'badge connected', text: '● live' },
    updating: { cls: 'badge updating', text: '↻ updating…' },
    disconnected: { cls: 'badge disconnected', text: '○ reconnecting…' },
  };
  on(EVENTS.SSE_STATUS, (status) => {
    const s = map[status] || map.disconnected;
    badge.className = s.cls;
    badge.textContent = s.text;
  });
}
