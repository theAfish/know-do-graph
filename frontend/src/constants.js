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
  generic: '#444c56',
};

export const ENTRY_TYPES = Object.keys(TYPE_COLORS);

export const colorFor = (type) => TYPE_COLORS[type] || TYPE_COLORS.generic;
