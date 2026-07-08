import { describe, expect, it, vi } from 'vitest';

vi.mock('../src/api.js', () => ({
  api: {
    getFullGraph: vi.fn(async () => ({
      nodes: [{ id: 'n1', title: 'Loaded Node' }],
      edges: [],
    })),
  },
}));

vi.mock('../src/graph/render.js', () => ({
  getSimulation: vi.fn(),
  highlightNode: vi.fn(),
  render: vi.fn(),
}));

vi.mock('../src/graph/interactions.js', () => ({
  attachNodeInteractions: vi.fn(),
}));

vi.mock('../src/ui/panel.js', () => ({
  closeDetail: vi.fn(),
  initPanel: vi.fn(),
}));

vi.mock('../src/ui/legend.js', () => ({ initLegend: vi.fn() }));
vi.mock('../src/ui/search.js', () => ({ initSearch: vi.fn() }));
vi.mock('../src/ui/shortcuts.js', () => ({ initShortcuts: vi.fn() }));
vi.mock('../src/ui/toolbar.js', () => ({ initToolbar: vi.fn() }));
vi.mock('../src/sse.js', () => ({ connectSSE: vi.fn() }));

import { attachNodeInteractions } from '../src/graph/interactions.js';
import { render } from '../src/graph/render.js';
import { loadGraph } from '../src/main.js';

describe('graph loading', () => {
  it('loads the API graph and renders it', async () => {
    document.body.innerHTML = '<div id="loading"></div><div id="error-banner" hidden></div>';

    await loadGraph();

    expect(render).toHaveBeenCalledWith([{ id: 'n1', title: 'Loaded Node' }], [], 0.8);
    expect(attachNodeInteractions).toHaveBeenCalled();
  });
});
