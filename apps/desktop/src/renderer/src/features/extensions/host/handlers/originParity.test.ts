// SOLUSDEV-235 / SEC-C1 — parity: `net.fetch` and `ui.openExternal` decide
// "may this extension reach that URL" through the SAME predicate module. If
// either handler grew its own check the two could drift apart.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createBridgeHost } from '../bridgeHost'
import * as originAllow from '../originAllow'
import type { BridgePolicy } from '../policySnapshot'
import { createOpenExternalLimiter, createRateLimiter } from '../rateLimiter'
import { fakeBridgeDeps } from '../testing/fakeBridgeDeps'

vi.mock('../originAllow', { spy: true })

const policy: BridgePolicy = {
  extensionId: 'bom',
  version: '1.2.0',
  projectId: 'p1',
  grantedScopes: [],
  grantedNetwork: ['https://api.octopart.com'],
  storeLinks: [],
  enabled: true,
  blocked: false,
  mode: 'widget'
}

const FRAME = { tag: 'frame' }

function call(method: string, url: string): Promise<void> {
  const host = createBridgeHost({
    frame: { postMessage: () => undefined, isSource: (s) => s === FRAME },
    policy,
    deps: fakeBridgeDeps(),
    rateLimiter: createRateLimiter({ now: () => 0 }),
    openExternalLimiter: createOpenExternalLimiter(() => 0)
  })
  return host.handleMessage({
    origin: 'null',
    source: FRAME,
    data: { v: 1, id: 'r', method, params: { url } }
  })
}

beforeEach(() => vi.clearAllMocks())

describe('origin allowlist parity', () => {
  it.each(['net.fetch', 'ui.openExternal'])('%s consults isGrantedOrigin', async (method) => {
    await call(method, 'https://api.octopart.com/x')
    expect(originAllow.isGrantedOrigin).toHaveBeenCalledWith(policy, 'https://api.octopart.com/x')
  })

  it('both methods agree on every URL in a mixed table', async () => {
    // https only: a non-https URL is invalid_params for ui.openExternal at the
    // schema step, before either handler runs.
    const urls = [
      'https://api.octopart.com/ok',
      'https://api.octopart.com:8443/port',
      'https://api.octopart.com.evil.io/',
      'https://169.254.169.254/'
    ]
    for (const url of urls) {
      await call('net.fetch', url)
      await call('ui.openExternal', url)
    }
    const results = vi.mocked(originAllow.isGrantedOrigin).mock.results.map((r) => r.value)
    expect(results).toHaveLength(urls.length * 2)
    for (let i = 0; i < results.length; i += 2) expect(results[i]).toBe(results[i + 1])
    expect(results.slice(0, 2)).toEqual([true, true])
    expect(results.slice(2)).not.toContain(true)
  })
})
