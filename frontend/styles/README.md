# Frontend CSS Map

- `base.css`: design tokens, reset rules, typography, and native element defaults.
- `layout.css`: top-level application layout, graph canvas, detail panel placement, and responsive shell behavior.
- `components.css`: toolbar controls, tooltip, detail panel content, forms, asset folders, and legend components.
- `graph.css`: SVG graph-specific node, edge, label, highlight, and label-toggle styles.

Keep selectors close to the owning module. Shared visual tokens belong in
`base.css`; behavior-specific selectors should stay beside their component area.
