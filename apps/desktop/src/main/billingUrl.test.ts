import { describe, it, expect } from 'vitest'
import { isAllowedBillingUrl, isAllowedCheckoutEntryUrl } from './billingUrl'

describe('isAllowedBillingUrl', () => {
  it('accepts https Stripe hosts', () => {
    expect(isAllowedBillingUrl('https://checkout.stripe.com/c/pay/cs_test_123')).toBe(true)
    expect(isAllowedBillingUrl('https://billing.stripe.com/p/session/abc')).toBe(true)
    expect(isAllowedBillingUrl('https://stripe.com/anything')).toBe(true)
  })

  it('rejects non-https schemes', () => {
    expect(isAllowedBillingUrl('http://checkout.stripe.com/x')).toBe(false)
    expect(isAllowedBillingUrl('javascript:alert(1)')).toBe(false)
    expect(isAllowedBillingUrl('file:///etc/passwd')).toBe(false)
  })

  it('rejects non-Stripe hosts (phishing/look-alike)', () => {
    expect(isAllowedBillingUrl('https://evil.example.com/pay')).toBe(false)
    expect(isAllowedBillingUrl('https://stripe.com.evil.com/pay')).toBe(false)
    expect(isAllowedBillingUrl('https://notstripe.com/pay')).toBe(false)
  })

  it('rejects malformed input', () => {
    expect(isAllowedBillingUrl('not a url')).toBe(false)
    expect(isAllowedBillingUrl('')).toBe(false)
  })
})

describe('isAllowedCheckoutEntryUrl', () => {
  it('accepts only the Stripe-hosted surfaces our API returns', () => {
    expect(isAllowedCheckoutEntryUrl('https://checkout.stripe.com/c/pay/cs_test_123')).toBe(true)
    expect(isAllowedCheckoutEntryUrl('https://billing.stripe.com/p/session/abc')).toBe(true)
    expect(isAllowedCheckoutEntryUrl('https://pay.stripe.com/x')).toBe(true)
  })

  it('rejects attacker-creatable Stripe surfaces (Payment Links) and the bare host', () => {
    // Anyone can mint a buy.stripe.com Payment Link with an arbitrary
    // post-payment redirect — never render one as our checkout (sec review M3).
    expect(isAllowedCheckoutEntryUrl('https://buy.stripe.com/test_abc')).toBe(false)
    expect(isAllowedCheckoutEntryUrl('https://stripe.com/anything')).toBe(false)
    expect(isAllowedCheckoutEntryUrl('https://js.stripe.com/v3')).toBe(false)
  })

  it('rejects non-https, non-Stripe, and malformed input', () => {
    expect(isAllowedCheckoutEntryUrl('http://checkout.stripe.com/x')).toBe(false)
    expect(isAllowedCheckoutEntryUrl('https://evil.example.com/pay')).toBe(false)
    expect(isAllowedCheckoutEntryUrl('not a url')).toBe(false)
  })
})
