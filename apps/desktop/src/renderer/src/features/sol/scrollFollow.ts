// Whether the SOL chat keeps following a streaming reply. The person's INPUT says when to stop: a
// wheel or trackpad scroll up, PageUp/ArrowUp/Home, or dragging the scrollbar away from the bottom.
// Scroll events alone cannot tell: settled rows use `content-visibility: auto` (main.css
// .sol-msg-settled), so when rows above re-measure the browser changes scrollHeight and clamps
// scrollTop by itself — seen live (SOLUSDEV-326) dropping from 3112 to 417 with nobody scrolling,
// which a distance or direction rule took for "scrolled up". A scroll event only ever RESUMES
// following, when the list reaches the bottom.

/** Stick-to-bottom margin: within this many px of the bottom counts as "at the bottom". */
export const FOLLOW_SLACK_PX = 48

const UPWARD_KEYS: ReadonlySet<string> = new Set(['PageUp', 'ArrowUp', 'Home'])

export interface ScrollGeometry {
  scrollTop: number
  scrollHeight: number
  clientHeight: number
}

export const isUpwardKey = (key: string): boolean => UPWARD_KEYS.has(key)

/** Following after a scroll event: at the bottom resumes it; dragging the scrollbar away from the
 *  bottom stops it; anything else (the browser moving the list) leaves it as it was. */
export function nextFollow(
  following: boolean,
  g: ScrollGeometry,
  input: { dragging: boolean }
): boolean {
  const atBottom = g.scrollHeight - g.scrollTop - g.clientHeight < FOLLOW_SLACK_PX
  if (atBottom) return true
  return input.dragging ? false : following
}
