import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources.hosted'
import { getDesktopOAuthBridge } from '../../lib/desktopBridge'
import { useAuthStore } from '../../store/authStore'
import { useOAuthConnect } from './useOAuthConnect'
vi.mock('../../lib/api/resources', async (original) => ({
  ...(await original<typeof import('../../lib/api/resources')>()),
  startOAuth: vi
    .fn()
    .mockResolvedValue({ authorize_url: 'https://example.test', state: 'account' }),
  exchangeOAuth: vi.fn().mockResolvedValue({ connection: { id: 'c1', account_login: 'test' } })
}))
vi.mock('../../lib/api/resources.hosted', () => ({
  getAccountHosted: vi.fn(),
  startAccountHosted: vi.fn(),
  exchangeAccountHosted: vi.fn()
}))
vi.mock('../../lib/desktopBridge', () => ({ getDesktopOAuthBridge: vi.fn() }))
beforeEach(() => {
  vi.clearAllMocks()
  useAuthStore.setState({ accessToken: 'session' })
  vi.mocked(resources.getAccountHosted).mockResolvedValue({
    server: 'fs',
    state: 'not_enabled',
    tool_count: 0
  })
})
it.each(['signout', 'unmount'])('cancels a pending hosted start on %s', async (reason) => {
  let finish!: (value: Awaited<ReturnType<typeof resources.startAccountHosted>>) => void
  vi.mocked(resources.startAccountHosted).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const awaitOAuth = vi.fn().mockResolvedValue({ code: 'code' })
  vi.mocked(getDesktopOAuthBridge).mockReturnValue({
    getConnectorRedirectUrl: async () => 'http://localhost/callback',
    awaitOAuth,
    cancelOAuth: vi.fn().mockResolvedValue(undefined)
  } as unknown as ReturnType<typeof getDesktopOAuthBridge>)
  const view = renderHook(() => useOAuthConnect())
  let work!: ReturnType<ReturnType<typeof useOAuthConnect>['startAccount']>
  await act(async () => {
    work = view.result.current.startAccount('cad', {
      hosted: { server: 'fs', display_name: 'FS', notice: '', subscribe_url: null }
    })
  })
  expect(resources.startAccountHosted).toHaveBeenCalledTimes(1)
  if (reason === 'signout') act(() => useAuthStore.setState({ accessToken: null }))
  else view.unmount()
  await act(async () => {
    finish({
      authorize_url: 'https://example.test/fs',
      state: 'hosted',
      redirect_uri: 'http://localhost/callback'
    })
    await work
  })
  expect(awaitOAuth).toHaveBeenCalledTimes(1)
  expect(resources.exchangeAccountHosted).not.toHaveBeenCalled()
})
