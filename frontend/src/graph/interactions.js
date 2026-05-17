import * as d3 from 'd3';
import { getSelections } from './render.js';
import { emit, EVENTS } from '../state.js';
import { showTooltip, moveTooltip, hideTooltip } from '../ui/tooltip.js';

let dragStartX, dragStartY, dragActive;

// Attach drag, click, hover handlers to whatever nodes currently exist.
// Call after every render() so the listeners bind to the fresh DOM.
export function attachNodeInteractions(simulationGetter) {
  const { sceneSel } = getSelections();
  if (!sceneSel) return;

  const nodeSel = sceneSel.selectAll('.node');

  nodeSel.call(
    d3
      .drag()
      .clickDistance(5)
      .on('start', (event) => {
        dragStartX = event.x;
        dragStartY = event.y;
        dragActive = false;
      })
      .on('drag', (event, d) => {
        if (!dragActive) {
          if (Math.hypot(event.x - dragStartX, event.y - dragStartY) < 5) return;
          dragActive = true;
          const sim = simulationGetter();
          sim?.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        }
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', (event, d) => {
        const sim = simulationGetter();
        if (!event.active) sim?.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      })
  );

  nodeSel
    .select('circle')
    .on('mouseover', (event, d) => showTooltip(event, d))
    .on('mousemove', (event) => moveTooltip(event))
    .on('mouseout', () => hideTooltip())
    .on('click', (event, d) => {
      event.stopPropagation();
      emit(EVENTS.NODE_SELECTED, d.id);
    });

  const { svgSel } = getSelections();
  svgSel.on('click', () => {
    hideTooltip();
    emit(EVENTS.NODE_CLEARED);
  });
}
