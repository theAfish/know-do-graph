import * as d3 from 'd3';
import { api } from '../api.js';
import { colorFor } from '../constants.js';
import { state, emit, on, EVENTS } from '../state.js';
import { getSelections } from '../graph/render.js';
import { debounce } from '../utils.js';

let searchInput;
let typeFilter;
let statsEl;

export function initSearch() {
  searchInput = document.getElementById('search-input');
  typeFilter = document.getElementById('type-filter');
  statsEl = document.getElementById('stats');

  searchInput.addEventListener('input', onSearchInput);
  typeFilter.addEventListener('change', () => {
    runFilters();
    emit(EVENTS.FILTERS_CHANGED);
  });

  on(EVENTS.GRAPH_LOADED, () => runFilters());
  on(EVENTS.SCORE_MODE_CHANGED, () => runFilters());
}

const apiSearchDebounced = debounce(async (q, type) => {
  try {
    const results = await api.searchEntries({ q, type });
    state.apiMatchIds = new Set(results.map((e) => e.id));
    state.searchScores = {};
    results.forEach((e) => {
      if (e._score != null) state.searchScores[e.id] = e._score;
    });
    runFilters();
    emit(EVENTS.FILTERS_CHANGED);
  } catch (err) {
    console.warn('API search failed:', err);
  }
}, 350);

function onSearchInput() {
  const q = searchInput.value.trim();
  const type = typeFilter.value;

  if (q.length >= 2 && !q.startsWith('#')) {
    apiSearchDebounced(q, type);
  } else {
    state.apiMatchIds = null;
    state.searchScores = {};
  }
  runFilters();
  emit(EVENTS.FILTERS_CHANGED);
}

function runFilters() {
  const { sceneSel } = getSelections();
  if (!sceneSel) return;

  const q = searchInput?.value.trim() || '';
  const type = typeFilter?.value || '';

  let tagFilter = null;
  let textQ = q.toLowerCase();
  if (q.startsWith('#')) {
    tagFilter = q.slice(1).toLowerCase().trim();
    textQ = '';
  }

  const visible = new Set();

  sceneSel.selectAll('.node').style('display', (d) => {
    let matchQ;
    if (tagFilter) {
      matchQ = Array.isArray(d.tags) && d.tags.some((t) => t.toLowerCase().includes(tagFilter));
    } else if (textQ) {
      const inTitle = d.title.toLowerCase().includes(textQ);
      const inSlug = (d.slug || '').toLowerCase().includes(textQ);
      const inTags = Array.isArray(d.tags) && d.tags.some((t) => t.toLowerCase().includes(textQ));
      const inApi = state.apiMatchIds ? state.apiMatchIds.has(d.id) : false;
      matchQ = inTitle || inSlug || inTags || inApi;
    } else {
      matchQ = true;
    }
    const matchType = !type || d.entry_type === type;
    const show = matchQ && matchType;
    if (show) visible.add(d.id);
    return show ? null : 'none';
  });

  sceneSel.selectAll('.edge').style('display', (e) => visiblePair(e, visible));
  sceneSel.selectAll('.edge-label').style('display', (e) => visiblePair(e, visible));

  applyScoreColoring(textQ || tagFilter);
  updateStats(visible.size, !!(textQ || tagFilter || type));
}

function visiblePair(e, visible) {
  const si = e.source.id || e.source;
  const ti = e.target.id || e.target;
  return visible.has(si) && visible.has(ti) ? null : 'none';
}

function applyScoreColoring(searching) {
  const { sceneSel } = getSelections();
  if (!sceneSel) return;

  if (state.scoreMode) {
    sceneSel
      .selectAll('.node circle')
      .attr('fill', (d) => {
        const s = state.searchScores[d.id];
        if (searching && s != null) return d3.interpolateInferno(0.2 + s * 0.75);
        return colorFor(d.entry_type);
      })
      .attr('stroke', (d) => {
        const s = state.searchScores[d.id];
        if (searching && s != null) {
          const c = d3.color(d3.interpolateInferno(0.2 + s * 0.75));
          return c ? c.brighter(0.6).toString() : '#fff';
        }
        return d3.color(colorFor(d.entry_type)).brighter(1).toString();
      });
    sceneSel.selectAll('.node .score-label').each(function (d) {
      const s = state.searchScores[d.id];
      const show = searching && s != null;
      d3.select(this)
        .style('display', show ? null : 'none')
        .text(show ? Math.round(s * 100) + '%' : '');
    });
  } else {
    sceneSel
      .selectAll('.node circle')
      .attr('fill', (d) => colorFor(d.entry_type))
      .attr('stroke', (d) => d3.color(colorFor(d.entry_type)).brighter(1).toString());
    sceneSel.selectAll('.node .score-label').style('display', 'none');
  }
}

function updateStats(visibleCount, filtering) {
  if (!statsEl) return;
  const total = state.allNodes.length;
  statsEl.textContent =
    filtering && visibleCount < total
      ? `${visibleCount}/${total} nodes · ${state.allEdges.length} edges`
      : `${total} nodes · ${state.allEdges.length} edges`;
}
