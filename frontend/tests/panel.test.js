import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/graph/render.js', () => ({
  clearHighlight: vi.fn(),
  highlightNode: vi.fn(),
  panZoomToNode: vi.fn(),
}));

vi.mock('../src/api.js', () => ({
  api: {
    assetUrl: vi.fn((entryId, folder, filename) => `/assets/${entryId}/${folder}/${filename}`),
    deleteEntry: vi.fn(async () => ({})),
    getEntry: vi.fn(),
    scriptDownloadUrl: vi.fn((entryId, filename) => `/scripts/${entryId}/${filename}`),
    syncRemote: vi.fn(async () => ({ result: { status: 'ok' } })),
    updateEntry: vi.fn(async (_id, payload) => payload),
  },
}));

import { api } from '../src/api.js';
import { EVENTS, on, state } from '../src/state.js';
import { initPanel, openDetail, renderDetailHtml } from '../src/ui/panel/index.js';

const entry = {
  id: 'n1',
  slug: 'alpha',
  title: 'Alpha Node',
  entry_type: 'capability',
  content: 'Hello',
  tags: ['tag-a'],
  aliases: [],
  metadata: { verification_status: 'unverified' },
  internal_refs: ['beta'],
};

function mountPanel() {
  document.body.innerHTML = `
    <aside id="detail" class="hidden" tabindex="-1">
      <h2 id="detail-title"></h2>
      <button id="detail-close" type="button">x</button>
      <div id="detail-body"></div>
    </aside>`;
}

describe('detail panel', () => {
  beforeEach(() => {
    mountPanel();
    state.allNodes = [entry, { id: 'n2', slug: 'beta', title: 'Beta Node', entry_type: 'tool' }];
    state.allEdges = [{ source: 'n1', target: 'n2', relation: 'uses' }];
    api.getEntry.mockResolvedValue({ ...entry });
    initPanel();
  });

  it('renders without inline onclick handlers', () => {
    const html = renderDetailHtml(entry, entry.id);

    expect(html).not.toContain('onclick=');
    expect(html).toContain('data-action="focus-node-slug"');
    expect(html).toContain('data-action="focus-node"');
  });

  it('opens, edits, and submits through delegated handlers', async () => {
    await openDetail('n1');
    expect(document.activeElement).toBe(document.querySelector('#detail'));
    document.querySelector('[data-action="edit-node"]').click();
    document.querySelector('input[name="title"]').value = 'Renamed Node';
    document.querySelector('#node-edit-form').dispatchEvent(new Event('submit', { bubbles: true }));
    await Promise.resolve();

    expect(api.updateEntry).toHaveBeenCalledWith(
      'n1',
      expect.objectContaining({ title: 'Renamed Node' }),
    );
  });

  it('deletes after confirmation and emits refresh', async () => {
    const refreshSpy = vi.fn();
    on(EVENTS.GRAPH_REFRESH, refreshSpy);
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    await openDetail('n1');
    document.querySelector('[data-action="delete-node"]').click();
    await Promise.resolve();

    expect(api.deleteEntry).toHaveBeenCalledWith('n1');
    expect(refreshSpy).toHaveBeenCalled();
    expect(document.querySelector('#detail').classList.contains('hidden')).toBe(true);
  });
});
