import {
  COLOR_MODES,
  LEVEL_COLORS,
  PUBLIC_TYPE_COLORS,
  VERIFICATION_COLORS,
} from '../constants.js';
import { byId } from '../dom.js';
import { EVENTS, on, state } from '../state.js';

export function initLegend() {
  renderLegend();
  on(EVENTS.COLOR_MODE_CHANGED, renderLegend);
  on(EVENTS.SCORE_MODE_CHANGED, renderLegend);
  on(EVENTS.FILTERS_CHANGED, renderLegend);
  on(EVENTS.GRAPH_LOADED, renderLegend);
}

function renderLegend() {
  const el = byId('legend');
  const mode = state.colorMode || 'type';
  const cfg = COLOR_MODES.find((m) => m.value === mode) || COLOR_MODES[0];

  if (cfg.kind === 'ramp') {
    renderRamp(el, cfg, mode);
    return;
  }

  if (mode === 'verification') {
    renderSwatches(el, 'Verification', VERIFICATION_COLORS);
    return;
  }

  if (mode === 'level') {
    renderSwatches(el, 'Skill level', LEVEL_COLORS);
    return;
  }

  renderSwatches(el, 'Entry types', PUBLIC_TYPE_COLORS, { includeVirtualHint: true });
}

function renderRamp(el, cfg, mode) {
  const bounds = rampBounds(mode);
  el.innerHTML = `
      <div class="leg-title">${cfg.label}</div>
      <svg class="score-ramp-svg" width="160" height="14">
        <defs>
          <linearGradient id="ramp-grad" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stop-color="#180f3e"/>
            <stop offset="28%" stop-color="#6a2089"/>
            <stop offset="56%" stop-color="#c84b6a"/>
            <stop offset="78%" stop-color="#f57c3b"/>
            <stop offset="100%" stop-color="#fde724"/>
          </linearGradient>
        </defs>
        <rect width="160" height="14" fill="url(#ramp-grad)" rx="3"/>
      </svg>
      <div class="ramp-labels"><span>${bounds.low}</span><span>${bounds.high}</span></div>`;
}

function rampBounds(mode) {
  const nodes = state.allNodes || [];
  if (mode === 'relevance') {
    const has = Object.keys(state.searchScores || {}).length > 0;
    return { low: has ? 'low' : 'search to score', high: 'high' };
  }
  if (mode === 'timestamp') {
    const ts = nodes
      .map((n) => n.timestamp && +new Date(n.timestamp))
      .filter((v) => v && !Number.isNaN(v));
    if (!ts.length) return { low: '-', high: '-' };
    return {
      low: new Date(Math.min(...ts)).toISOString().slice(0, 10),
      high: new Date(Math.max(...ts)).toISOString().slice(0, 10),
    };
  }
  if (mode === 'usage_count') {
    const vs = nodes.filter((n) => typeof n.usage_count === 'number').map((n) => n.usage_count);
    if (!vs.length) return { low: '-', high: '-' };
    return { low: String(Math.min(...vs)), high: String(Math.max(...vs)) };
  }
  if (mode === 'trust_score') {
    const vs = nodes.filter((n) => typeof n.trust_score === 'number').map((n) => n.trust_score);
    if (!vs.length) return { low: '-', high: '-' };
    return { low: Math.min(...vs).toFixed(2), high: Math.max(...vs).toFixed(2) };
  }
  return { low: 'low', high: 'high' };
}

function renderSwatches(el, title, colors, { includeVirtualHint = false } = {}) {
  el.innerHTML = `<div class="leg-title">${title}</div>`;
  for (const [key, color] of Object.entries(colors)) {
    const item = document.createElement('div');
    item.className = 'leg-item';
    item.innerHTML = `<div class="leg-dot" style="background:${color}"></div>${key}`;
    el.appendChild(item);
  }
  if (includeVirtualHint) {
    const item = document.createElement('div');
    item.className = 'leg-item';
    item.innerHTML = '<div class="leg-dot leg-dot-virtual"></div>virtual / placeholder';
    el.appendChild(item);
  }
}
