import { describe, expect, it, vi } from 'vitest';

import { api } from '../src/api.js';

function jsonResponse(body, init = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

describe('frontend API client', () => {
  it('loads the graph payload', async () => {
    const payload = { nodes: [{ id: 'n1', title: 'Node' }], edges: [] };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(payload)),
    );

    await expect(api.getFullGraph()).resolves.toEqual(payload);
    expect(fetch).toHaveBeenCalledWith('/graph/full');
  });

  it('unwraps paginated search results and keeps scores', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({ items: [{ id: 'n1', title: 'Node', _score: 0.75 }], total: 1 }),
      ),
    );

    await expect(api.searchEntries({ q: 'node', type: 'capability' })).resolves.toEqual([
      { id: 'n1', title: 'Node', _score: 0.75 },
    ]);
    expect(fetch).toHaveBeenCalledWith(
      '/entries/search?q=node&limit=200&include_scores=true&entry_type=capability',
    );
  });
});
