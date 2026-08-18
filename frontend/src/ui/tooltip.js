import { optionalById } from '../dom.js';
import { state } from '../state.js';
import { escHtml } from '../utils.js';

const tooltipEl = () => optionalById('tooltip');

export function showTooltip(event, node) {
  const tip = tooltipEl();
  if (!tip) return;
  const md = node.metadata || {};
  let html = `<div class="tt-title">${escHtml(node.title)}</div>`;
  html += row('type', node.entry_type || '-');
  html += row('slug', node.slug || '-');
  const relevance = state.searchScores[node.id];
  if (relevance != null) html += row('relevance', `${Math.round(relevance * 100)}%`);
  if (md.refinement_status) html += row('status', md.refinement_status);
  if (md.trust_score != null) html += row('trust', md.trust_score);
  if (md.usage_count != null) html += row('usage', md.usage_count);
  if (node.tags?.length) {
    const pills = node.tags.map((tag) => `<span>${escHtml(tag)}</span>`).join('');
    html += `<div class="tt-row"><span class="tt-key">tags</span><span class="tt-val tt-tags">${pills}</span></div>`;
  }
  tip.innerHTML = html;
  moveTooltip(event);
  tip.classList.add('visible');
}

function row(key, val) {
  return `<div class="tt-row"><span class="tt-key">${key}</span><span class="tt-val">${escHtml(val)}</span></div>`;
}

export function moveTooltip(event) {
  const tip = tooltipEl();
  if (!tip) return;
  const pad = 14;
  const tw = tip.offsetWidth;
  const th = tip.offsetHeight;
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  if (x + tw > window.innerWidth) x = event.clientX - tw - pad;
  if (y + th > window.innerHeight) y = event.clientY - th - pad;
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
}

export function hideTooltip() {
  tooltipEl()?.classList.remove('visible');
}
