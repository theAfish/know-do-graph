import { api } from '../api.js';
import { state, emit, on, EVENTS } from '../state.js';
import { getSelections } from '../graph/render.js';
import { applyColoring } from '../graph/coloring.js';
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
    queueDatasetSearch();
    runFilters();
    emit(EVENTS.FILTERS_CHANGED);
  });

  on(EVENTS.GRAPH_LOADED, () => runFilters());
  on(EVENTS.COLOR_MODE_CHANGED, () => applyColoring());
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
  state.searchQuery = q;

  if (usesDatasetSearch() && q.length >= 2) {
    state.apiMatchIds = null;
    state.searchScores = {};
    datasetSearchDebounced(q, type);
  } else if (q.length >= 2 && !q.startsWith('#')) {
    apiSearchDebounced(q, type);
  } else {
    state.apiMatchIds = null;
    state.searchScores = {};
    emit(EVENTS.GRAPH_SEARCH_CLEAR);
  }
  runFilters();
  emit(EVENTS.FILTERS_CHANGED);
}

const datasetSearchDebounced = debounce((q, type) => {
  emit(EVENTS.GRAPH_SEARCH_REQUEST, { q, type });
}, 350);

function usesDatasetSearch() {
  return state.dataset?.capabilities?.includes('search');
}

function queueDatasetSearch() {
  const q = searchInput?.value.trim() || '';
  state.searchQuery = q;
  if (usesDatasetSearch() && q.length >= 2) {
    datasetSearchDebounced(q, typeFilter?.value || '');
  }
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

  applyColoring();
  updateStats(visible.size, !!(textQ || tagFilter || type));
}

function visiblePair(e, visible) {
  const si = e.source.id || e.source;
  const ti = e.target.id || e.target;
  return visible.has(si) && visible.has(ti) ? null : 'none';
}

function updateStats(visibleCount, filtering) {
  if (!statsEl) return;
  const total = state.allNodes.length;
  statsEl.textContent =
    filtering && visibleCount < total
      ? `${visibleCount}/${total} nodes · ${state.allEdges.length} edges`
      : `${total} nodes · ${state.allEdges.length} edges`;
}
