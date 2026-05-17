import { TYPE_COLORS } from '../constants.js';
import { state, on, EVENTS } from '../state.js';

export function initLegend() {
  renderLegend();
  on(EVENTS.SCORE_MODE_CHANGED, renderLegend);
  on(EVENTS.FILTERS_CHANGED, renderLegend);
}

function renderLegend() {
  const el = document.getElementById('legend');
  if (!el) return;

  const showScore = state.scoreMode && Object.keys(state.searchScores).length > 0;

  if (showScore) {
    el.innerHTML = `
      <div class="leg-title">Relevance</div>
      <svg class="score-ramp-svg" width="160" height="14">
        <defs>
          <linearGradient id="ramp-grad" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%"   stop-color="#180f3e"/>
            <stop offset="28%"  stop-color="#6a2089"/>
            <stop offset="56%"  stop-color="#c84b6a"/>
            <stop offset="78%"  stop-color="#f57c3b"/>
            <stop offset="100%" stop-color="#fde724"/>
          </linearGradient>
        </defs>
        <rect width="160" height="14" fill="url(#ramp-grad)" rx="3"/>
      </svg>
      <div class="ramp-labels"><span>low</span><span>high</span></div>`;
    return;
  }

  el.innerHTML = '<div class="leg-title">Entry types</div>';
  Object.entries(TYPE_COLORS).forEach(([type, color]) => {
    const item = document.createElement('div');
    item.className = 'leg-item';
    item.innerHTML = `<div class="leg-dot" style="background:${color}"></div>${type}`;
    el.appendChild(item);
  });
}
