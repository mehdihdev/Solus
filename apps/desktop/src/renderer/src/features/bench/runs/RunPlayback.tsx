import { useMemo, useState } from 'react'
import type { RunManifest } from './runsApi'
import { SensorPreview } from './SensorPreview'
import { playbackFrame, playbackTimes } from './playback'
export function RunPlayback({
  manifest,
  projectId
}: {
  manifest: RunManifest
  projectId: string
}): React.JSX.Element {
  const [index, setIndex] = useState(0)
  const times = useMemo(() => playbackTimes(manifest), [manifest])
  const elapsed = times[Math.min(index, Math.max(0, times.length - 1))] ?? 0
  const frame = useMemo(() => playbackFrame(manifest, elapsed), [manifest, elapsed])
  const names = new Map(manifest.parts.map((part) => [part.device_id, part.name]))
  return (
    <section aria-label="Run playback">
      <h3>Playback</h3>
      {!times.length ? (
        <p>No recorded timestamps are available.</p>
      ) : (
        <>
          <label>
            Playback time{' '}
            <input
              aria-label="Playback time"
              type="range"
              min={0}
              max={times.length - 1}
              step={1}
              value={Math.min(index, times.length - 1)}
              onChange={(event) => setIndex(Number(event.target.value))}
            />
          </label>
          <output>{elapsed} ms elapsed</output>
          <p>
            Elapsed zero is the first numeric sample. Values appear only at their recorded
            timestamps.
          </p>
          <table>
            <thead>
              <tr>
                <th>Part / device</th>
                <th>Signal</th>
                <th>Value</th>
                <th>Unit</th>
              </tr>
            </thead>
            <tbody>
              {frame.rows.slice(0, 200).map((row, item) => (
                <tr key={`${row.device}:${row.signal}:${item}`}>
                  <td>{names.get(row.device) ?? row.device}</td>
                  <td>{row.signal}</td>
                  <td>{row.value}</td>
                  <td>{row.unit ?? 'Unknown'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!frame.rows.length && <p>No numeric samples at this timestamp.</p>}
          {frame.rows.length > 200 && (
            <p>Showing 200 of {frame.rows.length} values at this timestamp.</p>
          )}
          <h4>Sensor references</h4>
          {frame.sensors.length ? (
            <ul>
              {frame.sensors.slice(0, 100).map((sensor, item) => (
                <li key={`${sensor.artifact_id}:${item}`}>
                  {sensor.kind} · {sensor.device_id} · {sensor.timestamp} · artifact{' '}
                  {sensor.artifact_id}
                  <SensorPreview projectId={projectId} sensor={sensor} />
                </li>
              ))}
            </ul>
          ) : (
            <p>No sensor references at this timestamp.</p>
          )}
          {frame.sensors.length > 100 && <p>Showing 100 of {frame.sensors.length} references.</p>}
          <p>Open a recorded frame to view its camera image or LiDAR points at this timestamp.</p>
        </>
      )}
    </section>
  )
}
