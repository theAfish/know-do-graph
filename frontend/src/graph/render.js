import * as d3 from 'd3';
import { colorFor, TYPE_COLORS } from '../constants.js';
import { state, emit, EVENTS } from '../state.js';

let simulation;
let svgSel;
let sceneSel;
let zoom;
let rScale;
let degreeMap = {};

export function getSelections() {
  return { svgSel, sceneSel, zoom, rScale, degreeMap, simulation };
}

export function getSimulation() {
  return simulation;
}

export function render(nodes, edges, initialAlpha = 0.8) {
  state.allNodes = nodes;
  state.allEdges = edges;

  document.getElementById('loading').classList.add('hidden');

  const svgEl = document.getElementById('graph-svg');
  svgSel = d3.select(svgEl);
  sceneSel = svgSel.select('#scene');
  sceneSel.selectAll('*').remove();

  zoom = d3
    .zoom()
    .scaleExtent([0.05, 5])
    .on('zoom', (e) => sceneSel.attr('transform', e.transform));
  svgSel.call(zoom);

  // Compute node radii by degree
  degreeMap = {};
  nodes.forEach((n) => {
    degreeMap[n.id] = 0;
  });
  edges.forEach((e) => {
    const s = e.source.id || e.source;
    const t = e.target.id || e.target;
    degreeMap[s] = (degreeMap[s] || 0) + 1;
    degreeMap[t] = (degreeMap[t] || 0) + 1;
  });
  rScale = d3
    .scaleSqrt()
    .domain([0, d3.max(Object.values(degreeMap)) || 1])
    .range([7, 22]);

  // Edges
  const edgeSel = sceneSel
    .append('g')
    .attr('class', 'edges')
    .selectAll('.edge')
    .data(edges)
    .enter()
    .append('line')
    .attr('class', 'edge')
    .attr('stroke', 'var(--edge-color)')
    .attr('marker-end', 'url(#arrow)');

  // Edge labels
  const edgeLabelSel = sceneSel
    .append('g')
    .attr('class', 'edge-labels')
    .selectAll('.edge-label')
    .data(edges)
    .enter()
    .append('text')
    .attr('class', 'edge-label')
    .text((d) => d.relation || '');

  // Nodes
  const nodeSel = sceneSel
    .append('g')
    .attr('class', 'nodes')
    .selectAll('.node')
    .data(nodes, (d) => d.id)
    .enter()
    .append('g')
    .attr('class', 'node');

  nodeSel
    .append('circle')
    .attr('r', (d) => rScale(degreeMap[d.id] || 0))
    .attr('fill', (d) => colorFor(d.entry_type))
    .attr('stroke', (d) => d3.color(colorFor(d.entry_type)).brighter(1).toString());

  nodeSel
    .append('text')
    .attr('x', (d) => rScale(degreeMap[d.id] || 0) + 4)
    .text((d) => d.title)
    .style('display', state.showLabels ? null : 'none');

  nodeSel
    .append('text')
    .attr('class', 'score-label')
    .attr('y', (d) => rScale(degreeMap[d.id] || 0) + 4)
    .style('display', 'none');

  // Force simulation
  if (simulation) simulation.stop();
  simulation = d3
    .forceSimulation(nodes)
    .alpha(initialAlpha)
    .force(
      'link',
      d3
        .forceLink(edges)
        .id((d) => d.id)
        .distance(95)
    )
    .force('charge', d3.forceManyBody().strength(-240))
    .force('center', d3.forceCenter(svgEl.clientWidth / 2, svgEl.clientHeight / 2))
    .force(
      'collide',
      d3.forceCollide((d) => rScale(degreeMap[d.id] || 0) + 8)
    )
    .on('tick', () => {
      edgeSel
        .attr('x1', (d) => d.source.x)
        .attr('y1', (d) => d.source.y)
        .attr('x2', (d) => d.target.x)
        .attr('y2', (d) => d.target.y);

      edgeLabelSel
        .attr('x', (d) => (d.source.x + d.target.x) / 2)
        .attr('y', (d) => (d.source.y + d.target.y) / 2);

      nodeSel.attr('transform', (d) => `translate(${d.x},${d.y})`);
    });

  emit(EVENTS.GRAPH_LOADED, { nodes, edges });

  return { nodeSel, edgeSel, edgeLabelSel };
}

export function highlightNode(nodeId) {
  if (!sceneSel) return;
  const connectedIds = new Set([nodeId]);
  state.allEdges.forEach((e) => {
    const s = e.source.id || e.source;
    const t = e.target.id || e.target;
    if (s === nodeId) connectedIds.add(t);
    if (t === nodeId) connectedIds.add(s);
  });

  sceneSel
    .selectAll('.node')
    .classed('dimmed', (d) => !connectedIds.has(d.id))
    .classed('selected', (d) => d.id === nodeId);

  sceneSel
    .selectAll('.edge')
    .classed('highlighted', (e) => {
      const s = e.source.id || e.source;
      const t = e.target.id || e.target;
      return s === nodeId || t === nodeId;
    })
    .attr('stroke', (e) => {
      const s = e.source.id || e.source;
      const t = e.target.id || e.target;
      return s === nodeId || t === nodeId ? 'var(--accent)' : 'var(--edge-color)';
    })
    .attr('marker-end', (e) => {
      const s = e.source.id || e.source;
      const t = e.target.id || e.target;
      return s === nodeId || t === nodeId ? 'url(#arrow-hl)' : 'url(#arrow)';
    });
}

export function clearHighlight() {
  if (!sceneSel) return;
  sceneSel.selectAll('.node').classed('dimmed', false).classed('selected', false);
  sceneSel
    .selectAll('.edge')
    .classed('highlighted', false)
    .attr('stroke', 'var(--edge-color)')
    .attr('marker-end', 'url(#arrow)');
}

export function resetView() {
  if (!svgSel || !zoom) return;
  const svgEl = document.getElementById('graph-svg');
  const w = svgEl.clientWidth;
  const h = svgEl.clientHeight;
  svgSel
    .transition()
    .duration(400)
    .call(
      zoom.transform,
      d3.zoomIdentity
        .translate(w / 2, h / 2)
        .scale(1)
        .translate(-w / 2, -h / 2)
    );
}

export function panZoomToNode(nodeId) {
  if (!svgSel || !zoom) return;
  const node = state.allNodes.find((n) => n.id === nodeId);
  if (!node || node.x == null) return;
  const svgEl = document.getElementById('graph-svg');
  const w = svgEl.clientWidth;
  const h = svgEl.clientHeight;
  const scale = 1.2;
  svgSel
    .transition()
    .duration(450)
    .call(
      zoom.transform,
      d3.zoomIdentity.translate(w / 2 - node.x * scale, h / 2 - node.y * scale).scale(scale)
    );
}

// Expose color map for legend.
export { TYPE_COLORS };
