import { describe, it, expect } from 'vitest'
import { isAllowedBillingUrl } from './billingUrl'

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
