import { describe, expect, it } from 'vitest'
import { EMPTY_BENCH_VIEW, type BenchView, type SignalTarget } from '@solus/shared-types'
import { applyDisplayOps, displayFor, DEFAULT_DISPLAY } from './viewOps'

const target: SignalTarget = { kind: 'signal', device_id: 'usb:1/3', signal: 'a' }
const other: SignalTarget = { kind: 'signal', device_id: 'usb:1', signal: '3/a' }

describe('displayFor', () => {
  it('returns defaults for a target absent from the view', () => {
    expect(displayFor(EMPTY_BENCH_VIEW, target)).toEqual(DEFAULT_DISPLAY)
  })
})

describe('applyDisplayOps', () => {
  it('merges a patch into a new entry without mutating the view', () => {
    const before = EMPTY_BENCH_VIEW
    const after = applyDisplayOps(before, [
      { kind: 'set_display', target, patch: { pinned: true, unit: 'deg' } }
    ])
    expect(before.display).toEqual([])
    expect(displayFor(after, target)).toMatchObject({ pinned: true, unit: 'deg' })
    expect(displayFor(after, other)).toEqual(DEFAULT_DISPLAY)
    expect(after.version).toBe(before.version)
  })

  it('null resets a field and an all-default entry is removed', () => {
    const pinned = applyDisplayOps(EMPTY_BENCH_VIEW, [
      { kind: 'set_display', target, patch: { pinned: true } }
    ])
    const reset = applyDisplayOps(pinned, [
      { kind: 'set_display', target, patch: { pinned: null } }
    ])
    expect(reset.display).toEqual([])
  })

  it('keeps derived ops for the server (no optimistic derived change)', () => {
    const view: BenchView = { ...EMPTY_BENCH_VIEW, version: 2 }
    expect(applyDisplayOps(view, [{ kind: 'delete_derived', id: 'd1' }])).toEqual(view)
  })
})
