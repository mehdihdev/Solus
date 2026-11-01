// Live derived series for the Live Bench (architecture/bench-view.md §2): one
// DerivedSignalStream per mounted bench, re-fed whenever new device data arrives. The
// stream drops samples it has already seen, so re-feeding the same window is idempotent.
// A constant (zero-reference) derived signal has no device data to wait for, so while
// one exists the bench clock also re-feeds the stream every CONSTANT_TICK_MS (§4.6).
import { useEffect, useMemo, useRef, useState } from 'react'
import type { BenchViewDerived } from '@solus/shared-types'
import type { BenchDeviceRecent } from '../../../lib/api/resources'
import { DerivedSignalStream, type DerivedSeries } from './derivedSignals'

/** Bench clock period for constant derived signals. */
export const CONSTANT_TICK_MS = 1000

function useConstantTick(derived: readonly BenchViewDerived[]): number {
  const [tick, setTick] = useState(0)
  const hasConstant = derived.some((d) => d.refs.length === 0)
  useEffect(() => {
    if (!hasConstant) return
    const timer = setInterval(() => setTick((n) => n + 1), CONSTANT_TICK_MS)
    return () => clearInterval(timer)
  }, [hasConstant])
  return tick
}

export function useDerivedSeries(
  derived: readonly BenchViewDerived[],
  devices: Readonly<Record<string, BenchDeviceRecent>>
): DerivedSeries[] {
  const stream = useRef<DerivedSignalStream | null>(null)
  const tick = useConstantTick(derived)
  return useMemo(() => {
    stream.current ??= new DerivedSignalStream()
    return stream.current.update(
      derived.map(({ id, name, expression, unit }) => ({ id, name, expression, unit })),
      devices
    )
    // `tick` is a deliberate trigger: each bench-clock tick re-feeds the stream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [derived, devices, tick])
}
