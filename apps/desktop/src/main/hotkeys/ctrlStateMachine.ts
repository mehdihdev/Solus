// SOLUSDEV-252 S3: the Ctrl state machine (docs/architecture/sol-window.md §4).
// PURE — key/cursor events in, outputs out, time carried on every event. No
// Electron, no timers: the hook (keyHook.ts) and the sampler (cursorSampler.ts)
// feed it; hotkeys/index.ts acts on what comes out.
export interface Point {
  x: number
  y: number
}

export const TAP_MAX_MS = 250
export const TAP_MAX_MOVE_PX = 6
export const DOUBLE_TAP_WINDOW_MS = 350

export type CtrlEvent =
  | { type: 'ctrlDown'; t: number; at: Point }
  | { type: 'ctrlUp'; t: number }
  | { type: 'otherKeyDown'; t: number }
  | { type: 'cursor'; t: number; at: Point }

export type CtrlOutput =
  | { type: 'doubleTap' }
  | { type: 'gestureStart' }
  | { type: 'gestureEnd'; path: Point[] }
  | { type: 'passthrough' }

export type CtrlPhase = 'idle' | 'down' | 'chord' | 'gesturing'

export interface CtrlState {
  phase: CtrlPhase
  /** When Ctrl went down. */
  t0: number
  /** Cursor samples since Ctrl went down (first = where it went down). */
  path: Point[]
  /** Release time of a pending first tap, awaiting its double. */
  lastTapAt: number | null
}

export const IDLE: CtrlState = { phase: 'idle', t0: 0, path: [], lastTapAt: null }

type Transition = { state: CtrlState; outputs: CtrlOutput[] }

export const distance = (a: Point, b: Point): number => Math.hypot(a.x - b.x, a.y - b.y)

function onCtrlUp(s: CtrlState, t: number): Transition {
  const idle = { ...IDLE, lastTapAt: null }
  if (s.phase === 'gesturing')
    return { state: idle, outputs: [{ type: 'gestureEnd', path: s.path }] }
  if (s.phase !== 'down' || t - s.t0 > TAP_MAX_MS) return { state: idle, outputs: [] }
  // a tap: the second one inside the window is the summon
  if (s.lastTapAt !== null && t - s.lastTapAt <= DOUBLE_TAP_WINDOW_MS) {
    return { state: idle, outputs: [{ type: 'doubleTap' }] }
  }
  return { state: { ...idle, lastTapAt: t }, outputs: [] }
}

const stay = (s: CtrlState): Transition => ({ state: s, outputs: [] })

function onCtrlDown(s: CtrlState, t: number, at: Point): Transition {
  return s.phase === 'idle'
    ? { state: { ...s, phase: 'down', t0: t, path: [at] }, outputs: [] }
    : stay(s)
}

function onOtherKeyDown(s: CtrlState): Transition {
  // a chord (Ctrl+C…) is the OS app's business: observe, never consume
  return s.phase === 'down' || s.phase === 'gesturing'
    ? {
        state: { ...s, phase: 'chord', path: [], lastTapAt: null },
        outputs: [{ type: 'passthrough' }]
      }
    : stay(s)
}

function onCursor(s: CtrlState, t: number, at: Point): Transition {
  if (s.phase === 'gesturing') return { state: { ...s, path: [...s.path, at] }, outputs: [] }
  if (s.phase !== 'down') return stay(s)
  const path = [...s.path, at]
  const moved = distance(at, s.path[0] ?? at) > TAP_MAX_MOVE_PX
  return moved || t - s.t0 > TAP_MAX_MS
    ? { state: { ...s, phase: 'gesturing', path }, outputs: [{ type: 'gestureStart' }] }
    : { state: { ...s, path }, outputs: [] }
}

/** One transition. Returns the next state and the outputs it produced. */
export function step(s: CtrlState, e: CtrlEvent): Transition {
  switch (e.type) {
    case 'ctrlDown':
      return onCtrlDown(s, e.t, e.at)
    case 'otherKeyDown':
      return onOtherKeyDown(s)
    case 'cursor':
      return onCursor(s, e.t, e.at)
    case 'ctrlUp':
      return onCtrlUp(s, e.t)
  }
}

export interface CtrlStateMachine {
  feed(e: CtrlEvent): CtrlOutput[]
  phase(): CtrlPhase
}

/** Stateful wrapper over `step` for the wiring layer. */
export function createCtrlStateMachine(): CtrlStateMachine {
  let state = IDLE
  return {
    feed(e) {
      const next = step(state, e)
      state = next.state
      return next.outputs
    },
    phase: () => state.phase
  }
}
