/**
 * @template {HTMLElement} T
 * @param {string} id
 * @param {new (...args: never[]) => T} [ctor]
 * @returns {T}
 */
export function byId(id, ctor = HTMLElement) {
  const el = document.getElementById(id);
  if (!el) throw new Error(`Required DOM element #${id} was not found.`);
  if (!(el instanceof ctor)) {
    throw new Error(`Required DOM element #${id} has the wrong element type.`);
  }
  return el;
}

/**
 * @template {HTMLElement} T
 * @param {string} id
 * @param {new (...args: never[]) => T} [ctor]
 * @returns {T|null}
 */
export function optionalById(id, ctor = HTMLElement) {
  const el = document.getElementById(id);
  if (!el) return null;
  if (!(el instanceof ctor)) {
    throw new Error(`Optional DOM element #${id} has the wrong element type.`);
  }
  return el;
}

/**
 * @template {Element} T
 * @param {ParentNode} root
 * @param {string} selector
 * @param {new (...args: never[]) => T} [ctor]
 * @returns {T}
 */
export function queryRequired(root, selector, ctor = Element) {
  const el = root.querySelector(selector);
  if (!el) throw new Error(`Required DOM selector "${selector}" was not found.`);
  if (!(el instanceof ctor)) {
    throw new Error(`Required DOM selector "${selector}" has the wrong element type.`);
  }
  return el;
}
