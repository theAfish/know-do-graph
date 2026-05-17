# Frontend

Modular Vite-powered UI for the Know-Do Graph.

## Setup

```bash
cd frontend
npm install
```

## Development (with HMR)

Run the API and Vite dev server in parallel:

```bash
# terminal 1
python main.py serve

# terminal 2
cd frontend
npm run dev      # opens http://localhost:5173
```

Vite proxies `/entries`, `/graph`, `/agent`, `/mem`, `/remote`, `/health` to the API on `127.0.0.1:8000`.

## Production build

```bash
cd frontend
npm run build    # outputs to frontend/dist/
```

The FastAPI server (`python main.py serve`) automatically serves `frontend/dist/` at `/ui` when present.

## Layout

```
frontend/
  index.html             ← Vite entry (slim shell)
  src/
    main.js              ← bootstrap: wires modules, loads graph, opens SSE
    state.js             ← shared mutable state + pub/sub
    api.js               ← typed fetch wrappers
    sse.js               ← /graph/events client with auto-reconnect
    utils.js             ← escHtml, escAttr, debounce
    constants.js         ← TYPE_COLORS, ENTRY_TYPES
    graph/
      render.js          ← D3 force sim + DOM
      interactions.js    ← drag, zoom, highlight
    ui/
      toolbar.js         ← top bar + status badge
      search.js          ← search input + filter logic
      panel.js           ← right-side detail panel
      tooltip.js         ← hover tooltip
      legend.js          ← entry-type / relevance legend
      shortcuts.js       ← keyboard handling
  styles/
    base.css             ← variables, reset, typography
    layout.css           ← app shell + responsive
    components.css       ← toolbar, panel, tooltip, legend
    graph.css            ← nodes, edges, score-mode
```
