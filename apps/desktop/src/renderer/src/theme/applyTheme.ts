// Applies a theme + accent + density to the document by setting CSS custom
// properties on :root. Tailwind utilities (bg-bg, text-tx, …) and inline styles
// read these vars, so a single call re-skins the whole app at runtime.
// Ported from window.applySolusTheme in TestDesign/app/theme.js.

import {
  SOLUS_THEMES,
  SOLUS_ACCENTS,
  type ThemeId,
  type AccentId,
  type DensityId
} from './tokens.constants'

/** Build the {cssVar -> value} map for a theme/accent pair. Pure + testable. */
export function buildThemeVars(themeId: ThemeId, accentId: AccentId): Record<string, string> {
  const t = SOLUS_THEMES[themeId] ?? SOLUS_THEMES.dark
  const a = SOLUS_ACCENTS[accentId] ?? SOLUS_ACCENTS.amber
  return {
    '--bg': t.bg,
    '--sur': t.sur,
    '--sur2': t.sur2,
    '--bd': t.bd,
    '--tx': t.tx,
    '--mut': t.mut,
    '--ok': t.ok,
    '--warn': t.warn,
    '--err': t.err,
    '--sw': t.sw,
    '--ee': t.ee,
    '--me': t.me,
    '--rt': t.rt,
    '--acc': a.c,
    '--acc-ink': a.ink
  }
}

export function applyTheme(
  themeId: ThemeId,
  accentId: AccentId,
  density: DensityId = 'regular',
  doc: Document = document
): void {
  const root = doc.documentElement
  const vars = buildThemeVars(themeId, accentId)
  for (const [key, value] of Object.entries(vars)) {
    root.style.setProperty(key, value)
  }
  root.setAttribute('data-theme', themeId)
  root.setAttribute('data-density', density)
  doc.body.style.background = vars['--bg']
}
