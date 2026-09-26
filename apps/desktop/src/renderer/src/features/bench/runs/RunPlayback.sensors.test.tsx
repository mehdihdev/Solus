import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { fetchArtifactBlob } from '../../sol/solApi'
import { RunPlayback } from './RunPlayback'
import type { RunManifest } from './runsApi'

vi.mock('../../sol/solApi', () => ({ fetchArtifactBlob: vi.fn() }))
it('scrubs a joint sample, camera frame and LiDAR cloud at the same recorded time', async () => {
  const timestamp = '2026-01-01T00:00:01Z'
  const manifest: RunManifest = {
    schema_version: 1,
    robot_id: 'fixture',
    started_at: '2026-01-01T00:00:00Z',
    packets: [
      {
        device_id: 'joint',
        timestamp: '2026-01-01T00:00:00Z',
        values: { position: 0 },
        units: { position: 'rad' }
      },
      { device_id: 'joint', timestamp, values: { position: 1.25 }, units: { position: 'rad' } }
    ],
    sensors: [
      { artifact_id: 'camera', device_id: 'camera', kind: 'camera', timestamp },
      { artifact_id: 'cloud', device_id: 'lidar', kind: 'lidar', timestamp }
    ],
    parts: [],
    snapshots: []
  }
  URL.createObjectURL = vi.fn(() => 'blob:fixture-frame')
  URL.revokeObjectURL = vi.fn()
  const cloud = JSON.stringify({
    schema_version: 1,
    unit: 'm',
    points: [
      [0, 0, 0],
      [1, 1, 0.5]
    ]
  })
  vi.mocked(fetchArtifactBlob).mockImplementation(async (_project, id) =>
    id === 'camera'
      ? new Blob(['fixture'], { type: 'image/png' })
      : Object.assign(new Blob([cloud], { type: 'application/json' }), { text: async () => cloud })
  )
  render(<RunPlayback projectId="p" manifest={manifest} />)
  expect(screen.getByText('No sensor references at this timestamp.')).toBeInTheDocument()
  fireEvent.change(screen.getByRole('slider', { name: 'Playback time' }), {
    target: { value: '1' }
  })
  expect(screen.getByText('1000 ms elapsed')).toBeInTheDocument()
  expect(screen.getByRole('row', { name: 'joint position 1.25 rad' })).toBeInTheDocument()
  for (const button of screen.getAllByRole('button', { name: 'Open frame' }))
    fireEvent.click(button)
  expect(await screen.findByRole('img', { name: `camera at ${timestamp}` })).toHaveAttribute(
    'src',
    'blob:fixture-frame'
  )
  expect(
    await screen.findByRole('img', { name: 'LiDAR XY projection in metres' })
  ).toBeInTheDocument()
  expect(
    screen.getByText('2 recorded points · XY projection (m) · Z 0 to 0.5 m')
  ).toBeInTheDocument()
  fireEvent.change(screen.getByRole('slider', { name: 'Playback time' }), {
    target: { value: '0' }
  })
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:fixture-frame')
})
