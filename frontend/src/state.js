// Shared mutable state + a tiny pub/sub bus.

export const state = {
  allNodes: [],
  allEdges: [],
  selectedId: null,
  showLabels: true,
  colorMode: 'type',
  apiMatchIds: null, // Set<string> | null — IDs that matched the API content search
  searchScores: {}, // entry_id → normalized relevance (0..1)
  dataset: null, // /graph/dataset descriptor
  graphMetadata: {}, // metadata from the current /graph/full response
  isHierarchyView: false,
  isSearchView: false,
  searchQuery: '',
};

const listeners = new Map(); // event → Set<fn>

export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(fn);
  return () => listeners.get(event).delete(fn);
}

export function emit(event, payload) {
  const set = listeners.get(event);
  if (!set) return;
  for (const fn of set) {
    try {
      fn(payload);
    } catch (err) {
      console.error(`[state] listener for "${event}" threw:`, err);
    }
  }
}

// Event names — keep grepable
export const EVENTS = {
  GRAPH_LOADED: 'graph:loaded',
  GRAPH_REFRESH: 'graph:refresh',
  NODE_SELECTED: 'node:selected',
  NODE_CLEARED: 'node:cleared',
  FILTERS_CHANGED: 'filters:changed',
  SCORE_MODE_CHANGED: 'scoreMode:changed', // alias of COLOR_MODE_CHANGED, kept for compat
  COLOR_MODE_CHANGED: 'colorMode:changed',
  LABELS_CHANGED: 'labels:changed',
  SSE_STATUS: 'sse:status',
  HIERARCHY_REQUEST: 'hierarchy:request',
  GRAPH_SEARCH_REQUEST: 'graph:search-request',
  GRAPH_SEARCH_CLEAR: 'graph:search-clear',
};
