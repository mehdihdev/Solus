// SOLUSDEV-319 review HIGH-1: a packaged Solus.app checks its own signature
// (nested code and resources included) through the native module, once at
// launch and again at every drive-child spawn; until it passes, drive is off.
import { describe, expect, it, vi } from 'vitest'
import { createBundleCheck } from './driveBundleCheck'

const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0))

describe('createBundleCheck', () => {
  it('false until a check completes, then the answer; onChange on a change only', async () => {
    const checkOwnBundle = vi.fn(async () => true)
    const onChange = vi.fn()
    const b = createBundleCheck(() => ({ checkOwnBundle }), onChange)
    expect(b.ok()).toBe(false)
    expect(await b.check()).toBe(true)
    expect(b.ok()).toBe(true)
    await b.check()
    expect(onChange).toHaveBeenCalledTimes(1)
    checkOwnBundle.mockResolvedValueOnce(false)
    expect(await b.check()).toBe(false)
    expect(b.ok()).toBe(false)
    expect(onChange).toHaveBeenCalledTimes(2)
  })

  it('a missing module, a module without checkOwnBundle, or a throw is false', async () => {
    expect(await createBundleCheck(() => null).check()).toBe(false)
    expect(await createBundleCheck(() => ({})).check()).toBe(false)
    const throwing = createBundleCheck(() => ({
      checkOwnBundle: async () => {
        throw new Error('SecStaticCode failed')
      }
    }))
    expect(await throwing.check()).toBe(false)
  })

  it('a non-boolean answer is false', async () => {
    expect(await createBundleCheck(() => ({ checkOwnBundle: async () => 'yes' })).check()).toBe(
      false
    )
  })

  it('overlapping checks share one native call', async () => {
    const checkOwnBundle = vi.fn(async () => true)
    const b = createBundleCheck(() => ({ checkOwnBundle }))
    void b.check()
    void b.check()
    await flush()
    expect(checkOwnBundle).toHaveBeenCalledTimes(1)
  })
})
