import { describe, expect, it } from 'vitest'
import { isAllowedAppStoreUrl } from './appStoreUrl'

describe('isAllowedAppStoreUrl', () => {
  it('allows the Onshape App Store', () => {
    expect(
      isAllowedAppStoreUrl(
        'https://cad.onshape.com/appstore/apps/Onshape%20Labs/6a29aea7c03f8bf659841734'
      )
    ).toBe(true)
  })

  it('refuses plaintext, even on the right host', () => {
    expect(isAllowedAppStoreUrl('http://cad.onshape.com/appstore')).toBe(false)
  })

  it('refuses a subdomain, because this sends someone somewhere to pay', () => {
    // The narrow `isAllowedCheckoutEntryUrl` shape, not the wide one: anyone who
    // can stand up a subdomain must not inherit permission to be a payment page.
    expect(isAllowedAppStoreUrl('https://evil.cad.onshape.com/appstore')).toBe(false)
    expect(isAllowedAppStoreUrl('https://onshape.com/appstore')).toBe(false)
  })

  it('refuses a lookalike host', () => {
    expect(isAllowedAppStoreUrl('https://cad.onshape.com.evil.test/appstore')).toBe(false)
    expect(isAllowedAppStoreUrl('https://cad-onshape.com/appstore')).toBe(false)
  })

  it('refuses non-http schemes and junk', () => {
    for (const url of ['file:///etc/passwd', 'javascript:alert(1)', 'not a url', '']) {
      expect(isAllowedAppStoreUrl(url)).toBe(false)
    }
  })
})
