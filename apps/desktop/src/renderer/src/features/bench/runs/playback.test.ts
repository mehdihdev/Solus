import { expect, it } from 'vitest'
import { playbackFrame, playbackTimes } from './playback'
import type { RunManifest } from './runsApi'
const manifest: RunManifest = {
  schema_version: 1,
  robot_id: 'r',
  started_at: '2026-01-01T00:00:00Z',
  packets: [
    {
      device_id: 'servo',
      timestamp: '2026-01-01T00:00:10Z',
      values: { position: 1 },
      units: { position: 'rad' }
    },
    {
      device_id: 'servo',
      timestamp: '2026-01-01T00:00:11Z',
      values: { position: 2 },
      units: { position: 'rad' }
    }
  ],
  sensors: [
    { artifact_id: 'camera', timestamp: '2026-01-01T00:00:11Z', kind: 'camera', device_id: 'cam' }
  ],
  parts: [],
  snapshots: []
}
it('aligns recorded values and sensor references on elapsed time without interpolation', () => {
  expect(playbackTimes(manifest)).toEqual([0, 1000])
  expect(playbackFrame(manifest, 1000)).toMatchObject({
    rows: [{ device: 'servo', signal: 'position', value: 2, unit: 'rad' }],
    sensors: [{ artifact_id: 'camera' }]
  })
  expect(playbackFrame(manifest, 500)).toEqual({ rows: [], sensors: [] })
})
it('keeps missing units unknown and ignores invalid timestamps and nonfinite samples', () => {
  const bad = {
    ...manifest,
    packets: [{ device_id: 'servo', timestamp: 'invalid', values: { p: Infinity }, units: {} }]
  }
  expect(playbackFrame(bad, 0).rows).toEqual([])
})
