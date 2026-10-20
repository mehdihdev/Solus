// SOLUSDEV-236 — Enterprise "Contact sales" opens the mail client from main,
// since externalUrl.ts (SOLUSDEV-235 H2) deliberately refuses non-https.
import { describe, it, expect, vi } from 'vitest'
import { CONTACT_SALES_MAILTO, openContactSales } from './contactSales'

describe('openContactSales', () => {
  it('opens exactly the fixed mailto and reports ok', async () => {
    const open = vi.fn().mockResolvedValue(undefined)
    await expect(openContactSales({ open, isTrustedSender: () => true })).resolves.toEqual({
      ok: true
    })
    expect(open).toHaveBeenCalledExactlyOnceWith(
      'mailto:team@solusforge.com?subject=Enterprise%20plan'
    )
    expect(CONTACT_SALES_MAILTO).toBe('mailto:team@solusforge.com?subject=Enterprise%20plan')
  })

  it('ignores any renderer-supplied arguments', async () => {
    const open = vi.fn().mockResolvedValue(undefined)
    const deps = { open, isTrustedSender: () => true }
    await (openContactSales as (d: typeof deps, ...a: unknown[]) => Promise<unknown>)(
      deps,
      'https://evil.example',
      { url: 'file:///etc/passwd' }
    )
    expect(open).toHaveBeenCalledWith(CONTACT_SALES_MAILTO)
  })

  it('refuses a foreign sender without opening anything', async () => {
    const open = vi.fn()
    await expect(openContactSales({ open, isTrustedSender: () => false })).resolves.toEqual({
      ok: false
    })
    expect(open).not.toHaveBeenCalled()
  })

  it('returns ok:false when the opener rejects', async () => {
    const open = vi.fn().mockRejectedValue(new Error('no mail handler'))
    await expect(openContactSales({ open, isTrustedSender: () => true })).resolves.toEqual({
      ok: false
    })
  })
})
