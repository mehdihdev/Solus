import type { RunManifest, SensorReference } from './runsApi'
export interface PlaybackRow {
  device: string
  signal: string
  value: number
  unit: string | null
}
function startTime(manifest: RunManifest): number {
  const timestamps = manifest.packets
    .map((packet) => Date.parse(packet.timestamp))
    .filter(Number.isFinite)
  return timestamps.length ? Math.min(...timestamps) : Date.parse(manifest.started_at)
}
export function playbackTimes(manifest: RunManifest): number[] {
  const start = startTime(manifest)
  return [
    ...new Set(
      [...manifest.packets, ...manifest.sensors]
        .map((item) => Math.round(Date.parse(item.timestamp) - start))
        .filter(Number.isFinite)
    )
  ].sort((a, b) => a - b)
}
/** Exact recorded instants only: no interpolation, stale values or synthesized media. */
export function playbackFrame(
  manifest: RunManifest,
  elapsed: number
): { rows: PlaybackRow[]; sensors: SensorReference[] } {
  const start = startTime(manifest)
  const rows = manifest.packets
    .filter((packet) => Math.round(Date.parse(packet.timestamp) - start) === elapsed)
    .flatMap((packet) =>
      Object.entries(packet.values)
        .filter(([, value]) => Number.isFinite(value))
        .map(([signal, value]) => ({
          device: packet.device_id,
          signal,
          value,
          unit: packet.units[signal] ?? null
        }))
    )
  const sensors = manifest.sensors.filter(
    (sensor) => Math.round(Date.parse(sensor.timestamp) - start) === elapsed
  )
  return { rows, sensors }
}
