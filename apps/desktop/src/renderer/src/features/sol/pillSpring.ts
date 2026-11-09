// SOLUSDEV-319: the Ember Pill's panel-height spring, pure. A critically damped
// spring stepped in closed form: it never overshoots, it is stable at any frame
// length, and retargeting mid-flight keeps the current velocity — so a reply
// growing line by line unrolls as one motion instead of restarting an ease per line.

export interface SpringState {
  /** Current height, px. */
  readonly x: number
  /** Current velocity, px/s. */
  readonly v: number
}

/** Angular frequency (1/s): ~0.3 s to settle from any distance. */
export const SPRING_OMEGA = 24
/** A frame longer than this (a hidden or throttled window) counts as this long. */
export const SPRING_FRAME_MAX_S = 1 / 20
const SETTLE_PX = 0.5
const SETTLE_PX_PER_S = 10

/** Advance `dt` seconds toward `target`. */
export function stepSpring(state: SpringState, target: number, dt: number): SpringState {
  const t = Math.min(Math.max(dt, 0), SPRING_FRAME_MAX_S)
  const d = state.x - target
  const k = state.v + SPRING_OMEGA * d
  const decay = Math.exp(-SPRING_OMEGA * t)
  return { x: target + (d + k * t) * decay, v: (state.v - SPRING_OMEGA * k * t) * decay }
}

/** The settled state when close and slow enough to snap, else null. */
export function settle(state: SpringState, target: number): SpringState | null {
  return Math.abs(state.x - target) < SETTLE_PX && Math.abs(state.v) < SETTLE_PX_PER_S
    ? { x: target, v: 0 }
    : null
}
