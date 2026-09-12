// SOLUSDEV-233: citation display helper, in its own module so ContextPanel.tsx
// exports only components (react-refresh/only-export-components).

/** Strip the citation's [connector:ref] wrapper down to a readable label. */
export function citationLabel(citation: string): string {
  const inner = citation.replace(/^\[/, '').replace(/\]$/, '')
  const at = inner.indexOf(':')
  return at === -1 ? inner : inner.slice(at + 1)
}
