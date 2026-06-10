// Same-origin in prod (FastAPI serves dist) and in dev (Vite proxy).
const API_BASE = '';

async function jget(path) {
  const r = await fetch(`${API_BASE}${path}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${r.statusText}`);
  return r.json();
}

export const api = {
  getFullGraph: () => jget('/graph/full'),
  getEntry: (id) => jget(`/entries/${id}`),
  searchEntries: ({ q, type, limit = 200, includeScores = true }) => {
    const params = new URLSearchParams({ q, limit: String(limit) });
    if (includeScores) params.set('include_scores', 'true');
    if (type) params.set('entry_type', type);
    return jget(`/entries/search?${params}`);
  },
  scriptDownloadUrl: (entryId, filename) =>
    `${API_BASE}/entries/${entryId}/scripts/${encodeURIComponent(filename)}`,
  assetUrl: (entryId, folder, filename) =>
    `${API_BASE}/entries/${entryId}/assets/${encodeURIComponent(folder)}/${filename
      .split('/')
      .map(encodeURIComponent)
      .join('/')}`,
  listAssets: (entryId) => jget(`/entries/${entryId}/assets`),
  syncRemote: async (entryId, { force = true } = {}) => {
    const r = await fetch(
      `${API_BASE}/remote-sync/${encodeURIComponent(entryId)}?force=${force ? 'true' : 'false'}`,
      { method: 'POST' },
    );
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${r.statusText}`);
    return r.json();
  },
  eventsUrl: () => `${API_BASE}/graph/events`,
};
