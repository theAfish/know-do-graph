import { ENTRY_TYPES, COLOR_MODES } from '../constants.js';
import { state, on, emit, EVENTS } from '../state.js';
import { resetView } from '../graph/render.js';

export function initToolbar() {
  populateTypeFilter();
  populateColorMode();
  bindButtons();
  bindSSEStatus();
  applyLabelVisibility();
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

function populateColorMode() {
  const sel = document.getElementById('color-mode');
  if (!sel) return;
  sel.innerHTML = '';
  for (const m of COLOR_MODES) {
    const opt = document.createElement('option');
    opt.value = m.value;
    opt.textContent = m.label;
    if (m.value === state.colorMode) opt.selected = true;
    sel.appendChild(opt);
  }
}

function bindButtons() {
  const labelsBtn = document.getElementById('toggle-labels');
  const colorSel = document.getElementById('color-mode');
  const resetBtn = document.getElementById('reset-view');

  syncLabelBtn(labelsBtn);

  labelsBtn?.addEventListener('click', () => {
    state.showLabels = !state.showLabels;
    syncLabelBtn(labelsBtn);
    applyLabelVisibility();
    emit(EVENTS.LABELS_CHANGED, state.showLabels);
  });

  colorSel?.addEventListener('change', (e) => {
    state.colorMode = e.target.value || 'type';
    emit(EVENTS.COLOR_MODE_CHANGED, state.colorMode);
    // Kept for backward compat with any external listeners.
    emit(EVENTS.SCORE_MODE_CHANGED, state.colorMode);
  });

  resetBtn?.addEventListener('click', () => resetView());
}

function applyLabelVisibility() {
  // Toggle a single class on <body>; CSS hides both .node text and .edge-label
  // when labels are off. This keeps the toggle in one place and lets per-node
  // filtering (style display:none) keep working orthogonally.
  document.body.classList.toggle('labels-off', !state.showLabels);
}

function syncLabelBtn(btn) {
  if (!btn) return;
  btn.textContent = `Labels: ${state.showLabels ? 'on' : 'off'}`;
  btn.classList.toggle('active', state.showLabels);
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
