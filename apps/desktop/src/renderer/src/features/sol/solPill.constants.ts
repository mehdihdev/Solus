// SOLUSDEV-319: the Ember Pill's renderer-side height cap. Mirrors
// main/sol-window/pillGeometry.ts (solPill.constants.test.ts keeps them equal):
// the pill never takes more than min(620 px, 60 % of the screen's work area);
// past it the thread scrolls inside and the bar stays visible.
export const SOL_PILL_MAX_HEIGHT_PX = 620
export const SOL_PILL_MAX_SCREEN_FRACTION = 0.6

/** The cap for a screen whose available height is `availHeight` CSS px. */
export function pillHeightCap(availHeight: number): number {
  if (!Number.isFinite(availHeight) || availHeight <= 0) return SOL_PILL_MAX_HEIGHT_PX
  return Math.min(SOL_PILL_MAX_HEIGHT_PX, Math.floor(availHeight * SOL_PILL_MAX_SCREEN_FRACTION))
}
