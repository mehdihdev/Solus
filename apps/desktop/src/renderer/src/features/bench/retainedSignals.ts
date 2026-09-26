import type { BenchDeviceRecent } from '../../lib/api/resources'

/** Admit fresh channels, then preserve their identity through gaps. A replaced
 * device response or explicit device removal still removes that device's cards. */
export function retainedDevices(
  devices: BenchDeviceRecent[],
  previous: Readonly<Record<string, BenchDeviceRecent>>,
  now: number
): Record<string, BenchDeviceRecent> {
  return Object.fromEntries(
    devices.map((device) => {
      const known = new Map(
        (previous[device.device_id]?.signals ?? []).map((series) => [series.signal, series])
      )
      for (const series of device.signals) {
        const points = series.points.filter((point) => {
          const age = now - Date.parse(point.timestamp)
          return Number.isFinite(age) && age >= 0
        })
        if (
          points.some((point) => now - Date.parse(point.timestamp) <= 8000) ||
          known.has(series.signal)
        ) {
          if (!known.has(series.signal) && known.size >= 256) continue
          known.set(series.signal, {
            ...series,
            points: retainedPoints(points, known.get(series.signal))
          })
        }
      }
      return [device.device_id, { ...device, signals: [...known.values()] }]
    })
  )
}

function retainedPoints(
  points: BenchDeviceRecent['signals'][number]['points'],
  previous?: BenchDeviceRecent['signals'][number]
): BenchDeviceRecent['signals'][number]['points'] {
  return points.length ? points : (previous?.points ?? [])
}
