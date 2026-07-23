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

export function configureDataset(dataset, onChange) {
  const controls = document.getElementById('dataset-controls');
  const definitions = dataset?.controls || [];
  if (!controls) return;
  populateTypeFilter(dataset?.entry_types || ENTRY_TYPES);
  populateColorMode(dataset?.color_modes);
  if (typeof dataset?.presentation?.show_labels === 'boolean') {
    state.showLabels = dataset.presentation.show_labels;
    syncLabelBtn(document.getElementById('toggle-labels'));
    applyLabelVisibility();
  }
  controls.hidden = definitions.length === 0;
  controls.innerHTML = '';
  if (!definitions.length) return;

  const fields = [];
  for (const definition of definitions) {
    if (definition.type !== 'select' || !definition.parameter) continue;
    const label = document.createElement('label');
    label.textContent = `${definition.label || definition.parameter}:`;
    const select = document.createElement('select');
    select.setAttribute('aria-label', definition.label || definition.parameter);
    for (const optionDefinition of definition.options || []) {
      const option = document.createElement('option');
      option.value = String(optionDefinition.value);
      option.textContent = optionDefinition.label || String(optionDefinition.value);
      option.selected = optionDefinition.value === dataset.graph_defaults?.[definition.parameter];
      select.appendChild(option);
    }
    label.appendChild(select);
    controls.appendChild(label);
    fields.push({ parameter: definition.parameter, select });
  }

  const currentOptions = () => Object.fromEntries(fields.map(({ parameter, select }) => {
    const value = select.value;
    return [parameter, /^-?\d+(\.\d+)?$/.test(value) ? Number(value) : value];
  }));
  fields.forEach(({ select }) => { select.onchange = () => onChange(currentOptions()); });
}

function populateTypeFilter(types = ENTRY_TYPES) {
  const sel = document.getElementById('type-filter');
  if (!sel) return;
  const selected = sel.value;
  sel.innerHTML = '<option value="">All types</option>';
  for (const t of types) {
    const opt = document.createElement('option');
    opt.value = t;
    opt.textContent = t;
    sel.appendChild(opt);
  }
  if ([...types].includes(selected)) sel.value = selected;
}

function populateColorMode(allowedModes = null) {
  const sel = document.getElementById('color-mode');
  if (!sel) return;
  const modes = allowedModes ? COLOR_MODES.filter((mode) => allowedModes.includes(mode.value)) : COLOR_MODES;
  if (!modes.some((mode) => mode.value === state.colorMode)) state.colorMode = 'type';
  sel.innerHTML = '';
  for (const m of modes) {
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
