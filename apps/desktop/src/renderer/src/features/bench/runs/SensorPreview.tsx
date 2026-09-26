import { useEffect, useRef, useState } from 'react'
import { fetchArtifactBlob } from '../../sol/solApi'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../../graph/workspaceSession'
import type { SensorReference } from './runsApi'
import { MAX_SENSOR_BYTES, parsePointCloud, type Point } from './sensorMedia'

type Props = { projectId: string; sensor: SensorReference }
export function SensorPreview(props: Props): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  return (
    <Preview
      key={`${props.projectId}:${props.sensor.artifact_id}:${props.sensor.timestamp}:${generation}`}
      {...props}
      generation={generation}
    />
  )
}
function Preview({
  projectId,
  sensor,
  generation
}: Props & { generation: number }): React.JSX.Element {
  const [url, setUrl] = useState<string | null>(null)
  const [points, setPoints] = useState<Point[] | null>(null)
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const controller = useRef<AbortController | null>(null)
  const objectUrl = useRef<string | null>(null)
  useEffect(
    () => () => {
      controller.current?.abort()
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    },
    []
  )
  const open = async (): Promise<void> => {
    if (status === 'loading') return
    const request = new AbortController()
    controller.current = request
    setStatus('loading')
    try {
      const blob = await fetchArtifactBlob(projectId, sensor.artifact_id, {
        maxBytes: MAX_SENSOR_BYTES,
        signal: request.signal
      })
      if (request.signal.aborted || generation !== workspaceSessionGeneration()) return
      validateFrame(blob, sensor.kind)
      if (sensor.kind === 'camera') {
        const next = URL.createObjectURL(blob)
        objectUrl.current = next
        setUrl(next)
      } else {
        const text = await blob.text()
        if (request.signal.aborted || generation !== workspaceSessionGeneration()) return
        setPoints(parsePointCloud(text))
      }
      setStatus('ready')
    } catch {
      if (!request.signal.aborted && generation === workspaceSessionGeneration()) setStatus('error')
    }
  }
  return (
    <div>
      {status !== 'ready' && (
        <button disabled={status === 'loading'} onClick={() => void open()}>
          Open frame
        </button>
      )}
      {status === 'loading' && <p role="status">Loading recorded frame…</p>}
      {status === 'error' && <p role="alert">Recorded media is unavailable or unsupported.</p>}
      {url && (
        <img
          src={url}
          alt={`${sensor.device_id} at ${sensor.timestamp}`}
          style={{ maxWidth: '100%', maxHeight: 360 }}
        />
      )}
      {points && <PointCloud points={points} />}
    </div>
  )
}
function PointCloud({ points }: { points: Point[] }): React.JSX.Element {
  if (!points.length) return <p>Recorded point cloud is empty.</p>
  const xs = points.map((p) => p[0]),
    ys = points.map((p) => p[1]),
    zs = points.map((p) => p[2])
  const left = Math.min(...xs),
    bottom = Math.min(...ys)
  const span = Math.max(Math.max(...xs) - left, Math.max(...ys) - bottom, 0.001)
  return (
    <figure>
      <svg
        viewBox="0 0 400 400"
        role="img"
        aria-label="LiDAR XY projection in metres"
        style={{ maxWidth: 400, width: '100%', background: '#141b25' }}
      >
        {points.map(([x, y], index) => (
          <circle
            key={index}
            cx={10 + ((x - left) / span) * 380}
            cy={390 - ((y - bottom) / span) * 380}
            r={1.5}
            fill="#55d9d0"
          />
        ))}
      </svg>
      <figcaption>
        {points.length} recorded points · XY projection (m) · Z {Math.min(...zs)} to{' '}
        {Math.max(...zs)} m
      </figcaption>
    </figure>
  )
}

function validateFrame(blob: Blob, kind: SensorReference['kind']): void {
  if (blob.size > MAX_SENSOR_BYTES) throw new Error('Frame exceeds bound')
  if (kind === 'camera') {
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(blob.type))
      throw new Error('Unsupported raster')
  } else if (blob.type !== 'application/json') throw new Error('Unsupported point cloud')
}
