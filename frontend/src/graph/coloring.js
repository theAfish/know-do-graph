// Node coloring strategies. Selected via `state.colorMode` and the toolbar
// `#color-mode` <select>. The previous boolean `scoreMode` is now just one
// of several modes ("relevance").

import * as d3 from 'd3';
import { COLOR_MODES, TYPE_COLORS, VERIFICATION_COLORS, LEVEL_COLORS, colorFor } from '../constants.js';
import { state } from '../state.js';
import { getSelections } from './render.js';

const RAMP = (t) => d3.interpolateInferno(0.2 + Math.max(0, Math.min(1, t)) * 0.75);
const MISSING_FILL = '#2a2a2a';

let _scales = {};

function buildScales(nodes) {
  const ts = [];
  const usage = [];
  const trust = [];
  for (const n of nodes) {
    if (n.timestamp) {
      const t = +new Date(n.timestamp);
      if (!Number.isNaN(t)) ts.push(t);
    }
    if (typeof n.usage_count === 'number') usage.push(n.usage_count);
    if (typeof n.trust_score === 'number') trust.push(n.trust_score);
  }
  const extent = (arr) => (arr.length ? [Math.min(...arr), Math.max(...arr)] : null);
  _scales = {
    timestamp: extent(ts),
    usage_count: extent(usage),
    trust_score: extent(trust),
  };
}

function normalize(d, mode) {
  if (mode === 'relevance') {
    const s = state.searchScores[d.id];
    return s == null ? null : s;
  }
  if (mode === 'timestamp') {
    if (!d.timestamp) return null;
    const ext = _scales.timestamp;
    if (!ext) return null;
    const [a, b] = ext;
    if (b === a) return 0.5;
    const v = +new Date(d.timestamp);
    return Number.isNaN(v) ? null : (v - a) / (b - a);
  }
  if (mode === 'usage_count') {
    if (typeof d.usage_count !== 'number') return null;
    const ext = _scales.usage_count;
    if (!ext) return null;
    const [a, b] = ext;
    if (b === a) return 0.5;
    return (d.usage_count - a) / (b - a);
  }
  if (mode === 'trust_score') {
    if (typeof d.trust_score !== 'number') return null;
    return d.trust_score;
  }
  return null;
}

function isRamp(mode) {
  const m = COLOR_MODES.find((x) => x.value === mode);
  return m?.kind === 'ramp';
}

function fillFor(d, mode) {
  if (mode === 'type') return colorFor(d.entry_type);
  if (mode === 'level') {
    return LEVEL_COLORS[d.skill_level] || MISSING_FILL;
  }
  if (mode === 'verification') {
    return VERIFICATION_COLORS[d.verification_status] || TYPE_COLORS.generic;
  }
  const t = normalize(d, mode);
  if (t == null) return MISSING_FILL;
  return RAMP(t);
}

function rampLabel(d, mode, t) {
  if (mode === 'relevance') return Math.round(t * 100) + '%';
  if (mode === 'timestamp') {
    const dt = new Date(d.timestamp);
    return Number.isNaN(+dt) ? '' : dt.toISOString().slice(0, 10);
  }
  if (mode === 'usage_count') return String(d.usage_count);
  if (mode === 'trust_score') return d.trust_score.toFixed(2);
  return '';
}

export function applyColoring() {
  const { sceneSel } = getSelections();
  if (!sceneSel) return;

  buildScales(state.allNodes);
  const mode = state.colorMode || 'type';

  sceneSel
    .selectAll('.node circle')
    .attr('fill', (d) => (Array.isArray(d.tags) && d.tags.includes('placeholder') ? 'transparent' : fillFor(d, mode)))
    .attr('stroke', (d) => {
      const c = d3.color(fillFor(d, mode));
      return c ? c.brighter(1).toString() : '#fff';
    })
    .attr('stroke-dasharray', (d) => (Array.isArray(d.tags) && d.tags.includes('placeholder') ? '4 3' : null))
    .attr('stroke-width', (d) => (Array.isArray(d.tags) && d.tags.includes('placeholder') ? 2 : 1));

  const ramp = isRamp(mode);
  sceneSel.selectAll('.node .score-label').each(function (d) {
    const t = ramp ? normalize(d, mode) : null;
    d3.select(this)
      .style('display', t == null ? 'none' : null)
      .text(t == null ? '' : rampLabel(d, mode, t));
  });
}

// Re-exported so legend.js can introspect the active mode.
export { COLOR_MODES };
