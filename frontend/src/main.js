import { api } from './api.js';
import { state, on, EVENTS } from './state.js';
import { render, highlightNode, getSimulation } from './graph/render.js';
import { attachNodeInteractions } from './graph/interactions.js';
import { initToolbar } from './ui/toolbar.js';
import { initSearch } from './ui/search.js';
import { initPanel, closeDetail } from './ui/panel.js';
import { initLegend } from './ui/legend.js';
import { initShortcuts } from './ui/shortcuts.js';
import { connectSSE } from './sse.js';
import { debounce } from './utils.js';

function renderAndWire(nodes, edges, alpha = 0.8) {
  render(nodes, edges, alpha);
  attachNodeInteractions(getSimulation);
}

async function loadGraph() {
  try {
    const data = await api.getFullGraph();
    renderAndWire(data.nodes, data.edges);
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
    const data = await api.getFullGraph();
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

// ── Boot ────────────────────────────────────────────────────────────────────
initToolbar();
initSearch();
initPanel();
initLegend();
initShortcuts();

on(EVENTS.GRAPH_REFRESH, softRefresh);

loadGraph();
connectSSE(() => softRefresh());
