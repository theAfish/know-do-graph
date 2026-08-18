import { api } from './api.js';
import { state, on, EVENTS } from './state.js';
import { render, highlightNode, getSimulation } from './graph/render.js';
import { attachNodeInteractions } from './graph/interactions.js';
import { configureDataset, initToolbar } from './ui/toolbar.js';
import { initSearch } from './ui/search.js';
import { initPanel, closeDetail } from './ui/panel.js';
import { initLegend } from './ui/legend.js';
import { initShortcuts } from './ui/shortcuts.js';
import { connectSSE } from './sse.js';
import { debounce } from './utils.js';

let graphOptions = {};
let activeSearchRequest = 0;

function renderAndWire(nodes, edges, alpha = 0.8) {
  render(nodes, edges, alpha);
  attachNodeInteractions(getSimulation);
}

async function loadGraph() {
  try {
    const data = await api.getFullGraph(graphOptions);
    state.isHierarchyView = false;
    state.isSearchView = false;
    state.graphMetadata = data.metadata || {};
    renderAndWire(data.nodes, data.edges);
    showDatasetInfo(data.metadata);
    setOverviewButton(false);
  } catch (err) {
    showError(`Failed to load graph: ${err.message}.`);
  }
}

const softRefresh = debounce(async () => {
  const posMap = {};
  state.allNodes.forEach((n) => {
    if (n.x != null) posMap[n.id] = { x: n.x, y: n.y };
  });

  try {
    if (state.dataset?.read_only) return;
    const data = await api.getFullGraph(graphOptions);
    state.graphMetadata = data.metadata || {};
    data.nodes.forEach((n) => {
      if (posMap[n.id]) {
        n.x = posMap[n.id].x;
        n.y = posMap[n.id].y;
      }
    });
    renderAndWire(data.nodes, data.edges, 0.05);

    if (state.selectedId) {
      if (data.nodes.find((n) => n.id === state.selectedId)) {
        highlightNode(state.selectedId);
      } else {
        closeDetail();
      }
    }
  } catch (e) {
    console.warn('softRefresh failed:', e);
  }
}, 500);

function showError(msg) {
  document.getElementById('loading')?.classList.add('hidden');
  const banner = document.getElementById('error-banner');
  if (banner) {
    banner.textContent = `${msg} Make sure the API server is running.`;
    banner.hidden = false;
  }
}

function showDatasetInfo(metadata = {}) {
  const info = document.getElementById('dataset-info');
  if (!info) return;
  if (!state.dataset?.read_only) {
    info.hidden = true;
    return;
  }
  const total = Number(metadata.total_nodes || metadata.total_matches || 0).toLocaleString();
  const displayed = Number(metadata.displayed_nodes ?? metadata.displayed_children ?? 0).toLocaleString();
  const label = metadata.label || state.dataset?.label || 'Graph';
  info.textContent = metadata.kind === 'search'
    ? `${label}: ${displayed}/${total} matches`
    : metadata.kind === 'hierarchy'
    ? `${label}: ${displayed} constituents`
    : metadata.truncated
      ? `${label}: ${displayed}/${total} nodes`
      : `${label}: ${displayed} nodes`;
  info.hidden = false;
}

function setOverviewButton(show) {
  const button = document.getElementById('return-overview');
  if (button) button.hidden = !show;
}

async function showHierarchy({ nodeId, targetLevel }) {
  try {
    const data = await api.getHierarchy(nodeId, { targetLevel });
    state.isHierarchyView = true;
    state.isSearchView = false;
    state.graphMetadata = data.metadata || {};
    renderAndWire(data.nodes, data.edges);
    showDatasetInfo(data.metadata);
    setOverviewButton(true);
  } catch (err) {
    showError(`Failed to load hierarchy: ${err.message}.`);
  }
}

async function showDatasetSearch({ q, type }) {
  // The debounce callback can run after the input has changed or cleared.
  // Only render results for the query currently shown in the search box.
  if (q !== state.searchQuery) return;
  const requestId = ++activeSearchRequest;
  try {
    const data = await api.searchGraph({ ...graphOptions, q, entry_type: type });
    if (requestId !== activeSearchRequest || q !== state.searchQuery) return;
    state.isHierarchyView = false;
    state.isSearchView = true;
    state.graphMetadata = data.metadata || {};
    state.apiMatchIds = new Set(data.nodes.map((node) => node.id));
    renderAndWire(data.nodes, data.edges);
    showDatasetInfo(data.metadata);
    setOverviewButton(true);
  } catch (err) {
    if (requestId === activeSearchRequest) {
      showError(`Failed to search graph: ${err.message}.`);
    }
  }
}

function clearDatasetSearch() {
  activeSearchRequest += 1;
  if (!state.isSearchView) return;
  closeDetail();
  loadGraph();
}

async function configureGraphDataset() {
  const dataset = await api.getGraphDataset();
  state.dataset = dataset;
  graphOptions = dataset.graph_defaults || {};
  configureDataset(dataset, (options) => {
    graphOptions = options;
    closeDetail();
    activeSearchRequest += 1;
    if (dataset.capabilities?.includes('search') && state.searchQuery.length >= 2) {
      showDatasetSearch({
        q: state.searchQuery,
        type: document.getElementById('type-filter')?.value || '',
      });
    } else {
      loadGraph();
    }
  });
}

// ── Boot ────────────────────────────────────────────────────────────────────
async function boot() {
  initToolbar();
  initSearch();
  initPanel();
  initLegend();
  initShortcuts();
  on(EVENTS.GRAPH_REFRESH, softRefresh);
  on(EVENTS.HIERARCHY_REQUEST, showHierarchy);
  on(EVENTS.GRAPH_SEARCH_REQUEST, showDatasetSearch);
  on(EVENTS.GRAPH_SEARCH_CLEAR, clearDatasetSearch);
  document.getElementById('return-overview')?.addEventListener('click', () => {
    activeSearchRequest += 1;
    if (state.isSearchView) {
      const input = document.getElementById('search-input');
      if (input) input.value = '';
      state.searchQuery = '';
      state.apiMatchIds = null;
      state.searchScores = {};
    }
    closeDetail();
    loadGraph();
  });

  try {
    await configureGraphDataset();
  } catch (err) {
    console.warn('Could not describe graph dataset:', err);
  }
  loadGraph();
  connectSSE(() => softRefresh());
}

boot();
