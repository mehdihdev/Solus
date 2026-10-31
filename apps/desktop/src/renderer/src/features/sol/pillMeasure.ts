// SOLUSDEV-319: the Ember Pill's measured height (docs/architecture/sol-window.md
// "SOLUSDEV-319 Ember Pill"). The panel animates its height toward its body's
// natural height; main is told the target while growing (window first, content
// after) and the current height while shrinking (content first, window after).

export interface PillMeasure {
  /** What main should size the window to. */
  report: number
  /** Everything but the panel (bar, footer, padding, status lines). */
  chrome: number
}

const heightOf = (el: Element | null): number => el?.getBoundingClientRect().height ?? 0

export function measurePill(pill: HTMLElement): PillMeasure {
  const total = heightOf(pill)
  const panel = heightOf(pill.querySelector('.sol-pill-panel'))
  const body = heightOf(pill.querySelector('.sol-pill-panel-body'))
  return { report: Math.ceil(total + Math.max(0, body - panel)), chrome: total - panel }
}
