export const PUBLIC_TYPE_COLORS = {
  capability: '#238636',
  procedure: '#1f6feb',
  heuristic: '#db61a2',
  constraint: '#f85149',
};

export const LEGACY_TYPE_GROUPS = {
  workflow: '#238636',
  tool: '#1f6feb',
  repository: '#1f6feb',
  data: '#1f6feb',
  environment: '#f85149',
  dependency: '#f85149',
  analytical: '#db61a2',
  memory: '#6e7781',
  generic: '#444c56',
};

export const TYPE_COLORS = {
  ...PUBLIC_TYPE_COLORS,
  ...LEGACY_TYPE_GROUPS,
};

export const ENTRY_TYPES = ['capability', 'procedure', 'heuristic', 'constraint'];

export const canonicalTypeFor = (type) => {
  if (ENTRY_TYPES.includes(type)) return type;
  if (['workflow'].includes(type)) return 'capability';
  if (['tool', 'repository', 'data'].includes(type)) return 'procedure';
  if (['analytical'].includes(type)) return 'heuristic';
  if (['environment', 'dependency'].includes(type)) return 'constraint';
  return type || 'capability';
};

export const colorFor = (type) =>
  PUBLIC_TYPE_COLORS[canonicalTypeFor(type)] || TYPE_COLORS[type] || TYPE_COLORS.generic;

export const isVirtualNode = (node) => {
  const tags = Array.isArray(node?.tags) ? node.tags : [];
  return Boolean(
    node?.virtual ||
      node?.is_virtual ||
      node?.metadata?.virtual ||
      tags.some((tag) => ['placeholder', 'virtual'].includes(tag))
  );
};

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
