// Shared mutable state + a tiny pub/sub bus.

/** @type {import('./types.js').UiState} */
export const state = {
  allNodes: [],
  allEdges: [],
  selectedId: null,
  showLabels: true,
  colorMode: 'type',
  apiMatchIds: null,
  searchScores: {},
};

/** @type {Map<string, Set<(payload: unknown) => void>>} */
const listeners = new Map();

/**
 * @param {string} event
 * @param {(payload: unknown) => void} fn
 * @returns {() => void}
 */
export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(fn);
  return () => listeners.get(event).delete(fn);
}

/**
 * @param {string} event
 * @param {unknown} [payload]
 */
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

// Event names. Keep them grepable.
export const EVENTS = {
  GRAPH_LOADED: 'graph:loaded',
  GRAPH_REFRESH: 'graph:refresh',
  NODE_SELECTED: 'node:selected',
  NODE_CLEARED: 'node:cleared',
  FILTERS_CHANGED: 'filters:changed',
  SCORE_MODE_CHANGED: 'scoreMode:changed',
  COLOR_MODE_CHANGED: 'colorMode:changed',
  LABELS_CHANGED: 'labels:changed',
  SSE_STATUS: 'sse:status',
};
