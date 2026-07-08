import { describe, expect, it, vi } from 'vitest';

vi.mock('../src/graph/render.js', () => ({
  resetView: vi.fn(),
}));

vi.mock('../src/ui/panel.js', () => ({
  closeDetail: vi.fn(),
}));

import { resetView } from '../src/graph/render.js';
import { closeDetail } from '../src/ui/panel.js';
import { initShortcuts } from '../src/ui/shortcuts.js';

describe('keyboard shortcuts', () => {
  it('focuses search, closes panel, and resets view', () => {
    document.body.innerHTML = '<input id="search-input" />';
    const input = document.querySelector('#search-input');
    initShortcuts();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: '/' }));
    expect(document.activeElement).toBe(input);

    input.blur();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(closeDetail).toHaveBeenCalled();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'r' }));
    expect(resetView).toHaveBeenCalled();
  });
});
