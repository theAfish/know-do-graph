import { byId } from '../dom.js';
import { resetView } from '../graph/render.js';
import { closeDetail } from './panel.js';

export function initShortcuts() {
  document.addEventListener('keydown', (e) => {
    const target = e.target;
    const inField =
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement;

    if (e.key === '/' && !inField) {
      e.preventDefault();
      const input = byId('search-input', HTMLInputElement);
      input.focus();
      input.select();
      return;
    }

    if (e.key === 'Escape') {
      const input = byId('search-input', HTMLInputElement);
      if (document.activeElement === input) {
        input.blur();
      } else {
        closeDetail();
      }
      return;
    }

    if (e.key === 'r' && !inField && !e.metaKey && !e.ctrlKey) {
      resetView();
    }
  });
}
