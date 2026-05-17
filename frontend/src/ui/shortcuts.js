import { closeDetail } from './panel.js';
import { resetView } from '../graph/render.js';

export function initShortcuts() {
  document.addEventListener('keydown', (e) => {
    const target = e.target;
    const inField =
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement;

    // "/" focuses search (unless already typing)
    if (e.key === '/' && !inField) {
      e.preventDefault();
      const input = document.getElementById('search-input');
      input?.focus();
      input?.select();
      return;
    }

    // "Escape" closes panel + blurs search
    if (e.key === 'Escape') {
      const input = document.getElementById('search-input');
      if (document.activeElement === input) {
        input.blur();
      } else {
        closeDetail();
      }
      return;
    }

    // "r" resets view
    if (e.key === 'r' && !inField && !e.metaKey && !e.ctrlKey) {
      resetView();
    }
  });
}
