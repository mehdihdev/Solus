// Live derived series for the Live Bench (architecture/bench-view.md §2): one
// DerivedSignalStream per mounted bench, re-fed whenever new device data arrives. The
// stream drops samples it has already seen, so re-feeding the same window is idempotent.
import { useMemo, useRef } from 'react'
import type { BenchViewDerived } from '@solus/shared-types'
import type { BenchDeviceRecent } from '../../../lib/api/resources'
import { DerivedSignalStream, type DerivedSeries } from './derivedSignals'

export function useDerivedSeries(
  derived: readonly BenchViewDerived[],
  devices: Readonly<Record<string, BenchDeviceRecent>>
): DerivedSeries[] {
  const stream = useRef<DerivedSignalStream | null>(null)
  return useMemo(() => {
    stream.current ??= new DerivedSignalStream()
    return stream.current.update(
      derived.map(({ id, name, expression, unit }) => ({ id, name, expression, unit })),
      devices
    )
  }, [derived, devices])
}
