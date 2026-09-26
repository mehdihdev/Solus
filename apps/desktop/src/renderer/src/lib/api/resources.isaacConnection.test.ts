import { beforeEach, expect, it, vi } from 'vitest'
import { api } from './client'
import { getIsaacConnectionStatus } from './resources.isaacConnection'

vi.mock('./client', () => ({ api: { request: vi.fn() } }))
beforeEach(() => vi.clearAllMocks())

it('reads only the project application status with cancellation', async () => {
  const value = {
    bridge: 'connected',
    installation: 'installed',
    owned_session: 'not_running',
    streaming: 'none',
    reason: null
  }
  vi.mocked(api.request).mockResolvedValue(value)
  const signal = new AbortController().signal
  expect(await getIsaacConnectionStatus('project', signal)).toEqual(value)
  expect(api.request).toHaveBeenCalledWith('/projects/project/isaac/connection-status', { signal })
})

it.each([
  { installation: false },
  { streaming: 'live' },
  { owned_session: 'stopped' },
  { path: '/private' }
])('rejects invented states and raw fields %j', async (patch) => {
  vi.mocked(api.request).mockResolvedValue({
    bridge: 'connected',
    installation: 'unknown',
    owned_session: 'unknown',
    streaming: 'none',
    reason: 'observation_failed',
    ...patch
  })
  await expect(getIsaacConnectionStatus('project')).rejects.toThrow('status')
})
