import { describe, expect, it } from 'vitest'
import {
  DOUBLE_TAP_WINDOW_MS,
  TAP_MAX_MS,
  createCtrlStateMachine,
  type CtrlEvent,
  type CtrlOutput
} from './ctrlStateMachine'

const P = (x: number, y: number): { x: number; y: number } => ({ x, y })

function run(events: CtrlEvent[]): CtrlOutput[] {
  const machine = createCtrlStateMachine()
  return events.flatMap((e) => machine.feed(e))
}

const tap = (t: number): CtrlEvent[] => [
  { type: 'ctrlDown', t, at: P(0, 0) },
  { type: 'ctrlUp', t: t + 80 }
]

describe('ctrlStateMachine (docs/architecture/sol-window.md §4)', () => {
  it('double-tap → doubleTap', () => {
    const out = run([...tap(0), ...tap(200)])
    expect(out).toEqual([{ type: 'doubleTap' }])
  })

  it('tap, long pause, tap → no doubleTap', () => {
    const out = run([...tap(0), ...tap(80 + DOUBLE_TAP_WINDOW_MS + 1)])
    expect(out).toEqual([])
  })

  it('hold + move → gestureStart, ctrlUp → gestureEnd(path)', () => {
    const out = run([
      { type: 'ctrlDown', t: 0, at: P(0, 0) },
      { type: 'cursor', t: 16, at: P(3, 0) },
      { type: 'cursor', t: 32, at: P(20, 0) },
      { type: 'cursor', t: 48, at: P(40, 10) },
      { type: 'ctrlUp', t: 500 }
    ])
    expect(out).toEqual([
      { type: 'gestureStart' },
      { type: 'gestureEnd', path: [P(0, 0), P(3, 0), P(20, 0), P(40, 10)] }
    ])
  })

  it('Ctrl+C while down → passthrough only; no tap, no gesture', () => {
    const machine = createCtrlStateMachine()
    const out = [
      machine.feed({ type: 'ctrlDown', t: 0, at: P(0, 0) }),
      machine.feed({ type: 'cursor', t: 16, at: P(50, 50) }),
      machine.feed({ type: 'otherKeyDown', t: 30 }),
      machine.feed({ type: 'ctrlUp', t: 60 })
    ].flat()
    expect(out).toEqual([{ type: 'gestureStart' }, { type: 'passthrough' }])
    expect(machine.phase()).toBe('idle')
  })

  it('a tap followed by a chord does not summon', () => {
    const out = run([
      ...tap(0),
      { type: 'ctrlDown', t: 150, at: P(0, 0) },
      { type: 'otherKeyDown', t: 160 },
      { type: 'ctrlUp', t: 200 },
      // the chord cleared the pending tap: this single tap is a first tap again
      ...tap(260)
    ])
    expect(out).toEqual([{ type: 'passthrough' }])
  })

  it('ctrl held still for 2 s then released → no tap, no doubleTap', () => {
    const out = run([
      { type: 'ctrlDown', t: 0, at: P(5, 5) },
      { type: 'cursor', t: 1000, at: P(5, 5) },
      { type: 'ctrlUp', t: 2000 },
      ...tap(2100)
    ])
    expect(out.filter((o) => o.type === 'doubleTap')).toEqual([])
    // hold > TAP_MAX_MS arms gesturing; the stationary path is rejected downstream
    expect(out[0]).toEqual({ type: 'gestureStart' })
  })

  it('a slow release with no cursor samples is neither a tap nor a gesture', () => {
    expect(
      run([
        { type: 'ctrlDown', t: 0, at: P(0, 0) },
        { type: 'ctrlUp', t: TAP_MAX_MS + 1 }
      ])
    ).toEqual([])
  })
})
