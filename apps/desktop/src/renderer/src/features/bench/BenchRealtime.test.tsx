import { act, render, screen, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { BenchRealtimeContext, useBenchRealtime, useBenchRealtimeData } from './BenchRealtime'
import { connectBenchStream } from './benchStream'
import { useAuthStore } from '../../store/authStore'
import type { BenchSession } from '../../lib/api/resources'
vi.mock('./benchStream', () => ({ connectBenchStream: vi.fn(() => vi.fn()) }))
vi.mock('./signalAnomalies', () => ({ getSignalAnomalies: vi.fn(async () => []) }))
vi.mock('../../lib/api/resources', () => ({ getBenchDeviceRecent: vi.fn(async () => []) }))
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})
const sessions = [{ id: 's', status: 'active' }] as BenchSession[]
function Consumer(): React.JSX.Element {
  const value = useBenchRealtimeData('p')
  return <span>{value?.devices[0]?.device_id ?? 'empty'}</span>
}
function Harness(): React.JSX.Element {
  const value = useBenchRealtime('p', sessions)
  return (
    <BenchRealtimeContext.Provider value={value}>
      <Consumer />
      <Consumer />
    </BenchRealtimeContext.Provider>
  )
}
it('shares one session socket across consumers and discards old account callbacks', async () => {
  useAuthStore.setState({
    accessToken: 'fixture-a',
    status: 'authenticated',
    user: { email: 'a@example.test' }
  })
  render(<Harness />)
  expect(connectBenchStream).toHaveBeenCalledTimes(1)
  const callback = vi.mocked(connectBenchStream).mock.calls[0][0].receive
  await act(async () => callback([{ device_id: 'arm', resolved_entity_id: null, signals: [] }]))
  expect(screen.getAllByText('arm')).toHaveLength(2)
  act(() => useAuthStore.setState({ accessToken: 'fixture-b', user: { email: 'b@example.test' } }))
  expect(screen.getAllByText('empty')).toHaveLength(2)
  await act(async () =>
    callback([{ device_id: 'old-secret', resolved_entity_id: null, signals: [] }])
  )
  expect(screen.queryByText('old-secret')).not.toBeInTheDocument()
  expect(vi.mocked(connectBenchStream).mock.results[0].value).toHaveBeenCalledOnce()
})
