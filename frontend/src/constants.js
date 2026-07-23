export const TYPE_COLORS = {
  capability: '#238636',
  procedure: '#1f6feb',
  workflow: '#d29922',
  tool: '#8957e5',
  repository: '#bf8700',
  environment: '#1a7f5a',
  dependency: '#cf222e',
  data: '#388bfd',
  analytical: '#a371f7',
  memory: '#6e7781',
  heuristic: '#db61a2',
  constraint: '#f85149',
  generic: '#444c56',
};

export const ENTRY_TYPES = Object.keys(TYPE_COLORS);

function colorFromTypeName(type) {
  let hash = 0;
  for (const char of String(type || 'generic')) {
    hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0;
  }
  // D3's colour parser accepts the legacy comma form across supported versions.
  return `hsl(${Math.abs(hash) % 360}, 58%, 48%)`;
}

export const colorFor = (type) => TYPE_COLORS[type] || colorFromTypeName(type);

export function colorsForTypes(types) {
  return Object.fromEntries([...types].sort().map((type) => [type, colorFor(type)]));
}

export const VERIFICATION_COLORS = {
  unverified: '#6e7781',
  self_tested: '#1f6feb',
  peer_reviewed: '#238636',
  community_tested: '#a371f7',
  bugged: '#cf222e',
  deprecated: '#444c56',
};

// Hierarchical-memory level colors (progressive disclosure).
// L1 planner-facing → cool; L3/L4 operational sidecars → warm/red.
export const LEVEL_COLORS = {
  L1: '#238636', // Capability  (green)
  L2: '#1f6feb', // Procedure   (blue)
  L3: '#db61a2', // Heuristic   (pink)
  L4: '#f85149', // Constraint  (red)
};

// Color modes shown in the toolbar selector.
// `label` is the human-readable name; `kind` is "categorical" or "ramp".
export const COLOR_MODES = [
  { value: 'type', label: 'Entry type', kind: 'categorical' },
  { value: 'level', label: 'Skill level (L1\u2013L4)', kind: 'categorical' },
  { value: 'verification', label: 'Verification', kind: 'categorical' },
  { value: 'relevance', label: 'Relevance', kind: 'ramp' },
  { value: 'timestamp', label: 'Created', kind: 'ramp' },
  { value: 'usage_count', label: 'Usage count', kind: 'ramp' },
  { value: 'trust_score', label: 'Trust score', kind: 'ramp' },
];
