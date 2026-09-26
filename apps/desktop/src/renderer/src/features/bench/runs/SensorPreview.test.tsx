import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { fetchArtifactBlob } from '../../sol/solApi'
import { SensorPreview } from './SensorPreview'
vi.mock('../../sol/solApi', () => ({ fetchArtifactBlob: vi.fn() }))
const sensor = {
  kind: 'camera' as const,
  artifact_id: 'a',
  device_id: 'cam',
  timestamp: '2026-01-01T00:00:00Z'
}
beforeEach(() => {
  vi.mocked(fetchArtifactBlob).mockReset()
  URL.createObjectURL = vi.fn(() => 'blob:frame')
  URL.revokeObjectURL = vi.fn()
})
it('loads an explicitly requested raster frame and revokes it on unmount', async () => {
  vi.mocked(fetchArtifactBlob).mockResolvedValue(new Blob(['png'], { type: 'image/png' }))
  const view = render(<SensorPreview projectId="p" sensor={sensor} />)
  expect(fetchArtifactBlob).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Open frame' }))
  expect(await screen.findByRole('img')).toHaveAttribute('src', 'blob:frame')
  expect(fetchArtifactBlob).toHaveBeenCalledWith(
    'p',
    'a',
    expect.objectContaining({ maxBytes: 8388608 })
  )
  view.unmount()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:frame')
})
it('rejects active-content camera formats', async () => {
  vi.mocked(fetchArtifactBlob).mockResolvedValue(new Blob(['<svg/>'], { type: 'image/svg+xml' }))
  render(<SensorPreview projectId="p" sensor={sensor} />)
  fireEvent.click(screen.getByRole('button', { name: 'Open frame' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('unavailable or unsupported')
  expect(URL.createObjectURL).not.toHaveBeenCalled()
})
it('discards old scope loads', async () => {
  let finish!: (blob: Blob) => void
  vi.mocked(fetchArtifactBlob).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const view = render(<SensorPreview projectId="p" sensor={sensor} />)
  fireEvent.click(screen.getByRole('button', { name: 'Open frame' }))
  view.rerender(<SensorPreview projectId="other" sensor={sensor} />)
  await act(async () => finish(new Blob(['png'], { type: 'image/png' })))
  await waitFor(() => expect(screen.queryByRole('img')).toBeNull())
  expect(URL.createObjectURL).not.toHaveBeenCalled()
})
