import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DeviceBenchView, POLL_MS } from './DeviceBenchView'
import { getBenchDeviceRecent, type BenchDeviceRecent } from '../../lib/api/resources'
import { getSignalAnomalies } from './signalAnomalies'
import { useAuthStore } from '../../store/authStore'
vi.mock('../../lib/api/resources', async (original) => ({
  ...(await original<typeof import('../../lib/api/resources')>()),
  getBenchDeviceRecent: vi.fn()
}))
vi.mock('./signalAnomalies', async (original) => ({
  ...(await original<typeof import('./signalAnomalies')>()),
  getSignalAnomalies: vi.fn(async () => [])
}))
const recent = vi.mocked(getBenchDeviceRecent)
function channels(count: number): BenchDeviceRecent[] {
  return [
    {
      device_id: 'arm',
      resolved_entity_id: 'robot',
      signals: Array.from({ length: count }, (_, i) => ({
        signal: i === 12 ? 'force' : `motor-${i + 1}`,
        points: [-12000, -4000, 0].map((delta, at) => ({
          timestamp: new Date(Date.now() + delta).toISOString(),
          value: at + i,
          ...(i === 12 ? {} : { unit: 'rad' })
        }))
      }))
    }
  ]
}
beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  localStorage.clear()
  useAuthStore.setState({ user: { email: 'viewer@example.test' } })
  vi.mocked(getSignalAnomalies).mockResolvedValue([])
})
afterEach(() => vi.useRealTimers())
it('shows thirteen filled signal windows, flags missing units and scopes without renaming', async () => {
  recent.mockResolvedValue(channels(13))
  const confirm = vi.fn()
  const { container } = render(
    <DeviceBenchView projectId="p" deviceIds={['arm']} onConfirmBoard={confirm} robotCount={2} />
  )
  await act(() => vi.advanceTimersByTimeAsync(0))
  expect(screen.getByText('13 SIGNALS · CLICK TO SCOPE · CLICK NAME TO RENAME')).toBeInTheDocument()
  expect(screen.getAllByRole('region', { name: / signal$/ })).toHaveLength(13)
  expect(screen.getByText('no unit')).toHaveClass('bench-unit-unknown')
  expect(container.querySelectorAll('polygon')).toHaveLength(13)
  fireEvent.click(screen.getByRole('button', { name: 'Open hardware to confirm board identity' }))
  expect(confirm).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByRole('button', { name: 'Rename motor-1' }))
  expect(screen.getAllByRole('region', { name: / signal$/ })).toHaveLength(13)
  fireEvent.change(screen.getByLabelText('Signal name'), { target: { value: 'Shoulder' } })
  fireEvent.keyDown(screen.getByLabelText('Signal name'), { key: 'Enter' })
  fireEvent.click(
    within(screen.getByRole('region', { name: 'Shoulder signal' })).getByRole('button', {
      name: /Scope/
    })
  )
  expect(screen.getAllByRole('region', { name: / signal$/ })).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: 'Show all signals' }))
  expect(screen.getAllByRole('region', { name: / signal$/ })).toHaveLength(13)
  expect(screen.queryByRole('tab')).not.toBeInTheDocument()
})
it('updates channels automatically, uses an eight-second window, and pauses only this display', async () => {
  recent.mockResolvedValue(channels(13))
  const view = render(<DeviceBenchView projectId="p" deviceIds={['arm']} paused={false} />)
  await act(() => vi.advanceTimersByTimeAsync(0))
  expect(screen.getAllByRole('region', { name: / signal$/ })).toHaveLength(13)
  const points = screen.getAllByRole('img')[0].querySelector('polyline')?.getAttribute('points')
  expect(points?.split(' ')).toHaveLength(2)
  expect(points?.split(' ')[0].split(',')[0]).toBe('120.0')
  view.rerender(<DeviceBenchView projectId="p" deviceIds={['arm']} paused />)
  view.rerender(<DeviceBenchView projectId="p" deviceIds={['arm', 'new-device']} paused />)
  recent.mockResolvedValue(channels(14))
  await act(() => vi.advanceTimersByTimeAsync(POLL_MS * 2))
  expect(screen.getAllByRole('region', { name: / signal$/ })).toHaveLength(13)
  view.rerender(<DeviceBenchView projectId="p" deviceIds={['arm']} paused={false} />)
  await act(() => vi.advanceTimersByTimeAsync(0))
  expect(screen.getAllByRole('region', { name: / signal$/ })).toHaveLength(14)
  recent.mockImplementation(async () => channels(2))
  await act(() => vi.advanceTimersByTimeAsync(POLL_MS))
  expect(screen.getAllByRole('region', { name: / signal$/ })).toHaveLength(14)
  await act(() => vi.advanceTimersByTimeAsync(10_000))
  expect(screen.getAllByText(/STALE — waiting/)).toHaveLength(12)
})

it('offers board confirmation for a raw pin label even when its packet supplies a unit', async () => {
  const data = channels(1)
  data[0].signals[0].signal = 'PWM-9'
  recent.mockResolvedValue(data)
  render(<DeviceBenchView projectId="p" deviceIds={['arm']} onConfirmBoard={vi.fn()} />)
  await act(() => vi.advanceTimersByTimeAsync(0))
  expect(
    screen.getByRole('button', { name: 'Open hardware to confirm board identity' })
  ).toBeEnabled()
})

it('shows twelve primary windows, keeps diagnostics expandable and adds an unknown-unit sensor', async () => {
  const devices = ['leader', 'follower'].map((device_id) => ({
    device_id,
    resolved_entity_id: device_id,
    signals: Array.from({ length: 6 }, (_, i) =>
      ['position', 'load', 'temperature'].map((quantity) => ({
        signal: `joint-${i + 1}.${quantity}`,
        display_role: quantity === 'position' ? ('primary' as const) : ('diagnostic' as const),
        points: [{ timestamp: new Date().toISOString(), value: i }]
      }))
    ).flat()
  }))
  recent.mockResolvedValue(devices)
  render(<DeviceBenchView projectId="p" deviceIds={['leader', 'follower', 'sensor']} />)
  await act(() => vi.advanceTimersByTimeAsync(0))
  expect(screen.getAllByRole('region', { name: / signal$/ })).toHaveLength(12)
  const toggle = screen.getByRole('button', { name: 'Diagnostics · 24 signals' })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(toggle)
  expect(screen.getAllByRole('region', { name: / signal$/ })).toHaveLength(36)
  fireEvent.click(toggle)
  recent.mockResolvedValue([
    ...devices,
    {
      device_id: 'sensor',
      resolved_entity_id: 'sensor',
      signals: [{ signal: 'pressure', points: [{ timestamp: new Date().toISOString(), value: 3 }] }]
    }
  ])
  await act(() => vi.advanceTimersByTimeAsync(POLL_MS))
  expect(screen.getAllByRole('region', { name: / signal$/ })).toHaveLength(13)
  expect(
    within(screen.getByRole('region', { name: 'pressure signal' })).getByText('no unit')
  ).toBeInTheDocument()
  expect(screen.getByText(/Watching 37 signals/)).toBeInTheDocument()
})

it('keeps diagnostic findings visible while their signal windows are collapsed', async () => {
  const at = new Date().toISOString()
  recent.mockResolvedValue([
    {
      device_id: 'device',
      resolved_entity_id: 'part',
      signals: [
        { signal: 'position', points: [{ timestamp: at, value: 1 }] },
        { signal: 'health', display_role: 'diagnostic', points: [{ timestamp: at, value: 70 }] }
      ]
    }
  ])
  vi.mocked(getSignalAnomalies).mockResolvedValue([
    { kind: 'stream_gap', device_id: 'device', signal: 'health', at, value: null }
  ])
  render(<DeviceBenchView projectId="p" deviceIds={['device']} />)
  await act(() => vi.advanceTimersByTimeAsync(0))
  expect(screen.queryByRole('region', { name: 'health signal' })).not.toBeInTheDocument()
  expect(screen.getByText('stream gap')).toBeInTheDocument()
  expect(screen.getByText('health · device')).toBeInTheDocument()
})
