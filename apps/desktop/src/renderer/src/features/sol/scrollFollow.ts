// Whether the SOL chat keeps following a streaming reply after a scroll event — read from the
// person's DIRECTION, not from the distance to the bottom alone. Settled rows use
// `content-visibility: auto` (main.css .sol-msg-settled) and render at an estimated height until
// they come into view; when they do, the list grows without anyone scrolling, and a distance-only
// rule took that for "scrolled up" and stopped following (seen live with a tall Thinking block,
// SOLUSDEV-326). Only an actual scroll up stops it; reaching the bottom resumes it.

/** Stick-to-bottom margin: within this many px of the bottom counts as "at the bottom". */
export const FOLLOW_SLACK_PX = 48
/** A scroll up by more than this many px is the person's own. */
const UP_SLACK_PX = 2

export interface ScrollGeometry {
  scrollTop: number
  scrollHeight: number
  clientHeight: number
}

export interface FollowState {
  following: boolean
  /** Where the list was after the last scroll or pin. */
  lastTop: number
}

/** The scrollTop of a list pinned to its bottom. */
export const bottomTop = (g: ScrollGeometry): number => Math.max(0, g.scrollHeight - g.clientHeight)

export function nextFollow(prior: FollowState, g: ScrollGeometry): FollowState {
  const atBottom = g.scrollHeight - g.scrollTop - g.clientHeight < FOLLOW_SLACK_PX
  const scrolledUp = g.scrollTop < prior.lastTop - UP_SLACK_PX
  const following = atBottom || (prior.following && !scrolledUp)
  return { following, lastTop: g.scrollTop }
}
