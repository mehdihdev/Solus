import { expect, it, vi } from 'vitest'
import { accountAddOnStep, type AccountAddOnDeps } from './accountAddOnStep'
import type { HostedStatus } from '../../lib/api/resources'
const status = (state: HostedStatus['state']): HostedStatus => ({
  server: 'fs',
  state,
  tool_count: 2
})
function deps(): AccountAddOnDeps {
  return {
    hosted: {
      server: 'fs',
      display_name: 'FeatureScript',
      notice: 'Runs as you',
      subscribe_url: null
    },
    bridge: {
      awaitOAuth: vi.fn().mockResolvedValue({ code: 'code' })
    } as unknown as AccountAddOnDeps['bridge'],
    isCancelled: () => false,
    onProgress: vi.fn(),
    api: {
      getAccountHosted: vi.fn().mockResolvedValue(status('not_connected')),
      startAccountHosted: vi
        .fn()
        .mockResolvedValue({ authorize_url: 'https://example.test/auth', state: 's' }),
      exchangeAccountHosted: vi.fn().mockResolvedValue(status('ready'))
    }
  }
}
it('automatically performs the hosted leg and reports verified readiness', async () => {
  const d = deps()
  expect(await accountAddOnStep(d)('c1')).toBe('FeatureScript enabled')
  expect(d.api.startAccountHosted).toHaveBeenCalledWith('c1', 'fs')
  expect(d.api.exchangeAccountHosted).toHaveBeenCalledWith('c1', 'fs', { state: 's', code: 'code' })
})
it('skips consent when the account grant is already ready', async () => {
  const d = deps()
  vi.mocked(d.api.getAccountHosted).mockResolvedValue(status('ready'))
  expect(await accountAddOnStep(d)('c1')).toBe('FeatureScript enabled')
  expect(d.api.startAccountHosted).not.toHaveBeenCalled()
})
it('does not open a browser after cancellation during the status read', async () => {
  const d = deps()
  let cancelled = false
  d.isCancelled = () => cancelled
  vi.mocked(d.api.getAccountHosted).mockImplementation(async () => {
    cancelled = true
    return status('not_connected')
  })
  await accountAddOnStep(d)('c1')
  expect(d.api.startAccountHosted).not.toHaveBeenCalled()
})
it('reports incomplete setup without claiming it is enabled', async () => {
  const d = deps()
  vi.mocked(d.api.exchangeAccountHosted).mockResolvedValue(status('subscription_required'))
  expect(await accountAddOnStep(d)('c1')).toContain('setup incomplete')
})
