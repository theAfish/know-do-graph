import { beforeEach, describe, expect, it, vi } from 'vitest';

const styleCalls = [];

vi.mock('../src/graph/render.js', () => ({
  getSelections: () => ({
    sceneSel: {
      selectAll: (selector) => ({
        style: (_prop, fn) => {
          styleCalls.push({ selector, fn });
          if (selector === '.node') {
            state.allNodes.forEach((node) => fn(node));
          }
          if (selector === '.edge' || selector === '.edge-label') {
            state.allEdges.forEach((edge) => fn(edge));
          }
          return null;
        },
      }),
    },
  }),
}));

vi.mock('../src/graph/coloring.js', () => ({
  applyColoring: vi.fn(),
}));

vi.mock('../src/api.js', () => ({
  api: {
    searchEntries: vi.fn(async () => [{ id: 'n2', _score: 0.9 }]),
  },
}));

import { api } from '../src/api.js';
import { state } from '../src/state.js';
import { initSearch } from '../src/ui/search.js';

describe('search UI', () => {
  beforeEach(() => {
    styleCalls.length = 0;
    document.body.innerHTML = `
      <input id="search-input" />
      <select id="type-filter"><option value="">All</option><option value="tool">tool</option></select>
      <span id="stats"></span>`;
    state.allNodes = [
      { id: 'n1', title: 'Alpha', slug: 'alpha', entry_type: 'capability', tags: ['one'] },
      { id: 'n2', title: 'Beta', slug: 'beta', entry_type: 'tool', tags: ['two'] },
    ];
    state.allEdges = [{ source: 'n1', target: 'n2' }];
    state.apiMatchIds = null;
    state.searchScores = {};
    initSearch();
  });

  it('filters graph selections and updates stats', () => {
    const input = document.querySelector('#search-input');
    input.value = '#two';
    input.dispatchEvent(new Event('input', { bubbles: true }));

    const nodeStyle = styleCalls.find((call) => call.selector === '.node');
    expect(nodeStyle.fn(state.allNodes[0])).toBe('none');
    expect(nodeStyle.fn(state.allNodes[1])).toBeNull();
    expect(document.querySelector('#stats').textContent).toBe('1/2 nodes · 1 edges');
  });

  it('runs API search for content queries', async () => {
    vi.useFakeTimers();
    const input = document.querySelector('#search-input');
    input.value = 'beta';
    input.dispatchEvent(new Event('input', { bubbles: true }));

    await vi.advanceTimersByTimeAsync(400);

    expect(api.searchEntries).toHaveBeenCalledWith({ q: 'beta', type: '' });
    expect(state.apiMatchIds.has('n2')).toBe(true);
    expect(state.searchScores.n2).toBe(0.9);
  });
});
