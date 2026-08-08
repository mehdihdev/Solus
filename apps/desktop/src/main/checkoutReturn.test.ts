import { describe, expect, test } from 'vitest'
import { classifyCheckoutNavigation } from './checkoutReturn'

describe('classifyCheckoutNavigation', () => {
  test('detects success marker in a plain query', () => {
    expect(classifyCheckoutNavigation('https://app.solus.dev/billing?checkout=success')).toBe(
      'success'
    )
  })

  test('detects cancel marker in a plain query', () => {
    expect(classifyCheckoutNavigation('https://app.solus.dev/billing?checkout=cancel')).toBe(
      'cancel'
    )
  })

  test('detects markers inside a hash-router fragment', () => {
    // The renderer uses hash routing, so the server's configured return URLs
    // carry the query INSIDE the fragment: /#/billing?checkout=success
    expect(classifyCheckoutNavigation('http://localhost:5173/#/billing?checkout=success')).toBe(
      'success'
    )
    expect(classifyCheckoutNavigation('http://localhost:5173/#/billing?checkout=cancel')).toBe(
      'cancel'
    )
  })

  test('detects the billing-portal return marker', () => {
    expect(classifyCheckoutNavigation('http://localhost:5173/#/billing?portal=return')).toBe(
      'return'
    )
    expect(classifyCheckoutNavigation('https://app.solus.dev/billing?portal=return')).toBe('return')
  })

  test('ignores ordinary Stripe navigation', () => {
    expect(
      classifyCheckoutNavigation('https://checkout.stripe.com/c/pay/cs_test_abc#fidkdW')
    ).toBeNull()
    expect(classifyCheckoutNavigation('https://billing.stripe.com/p/session/xyz')).toBeNull()
  })

  test('ignores 3DS / bank-auth redirects without markers', () => {
    // Payment authentication may bounce the top frame through non-Stripe hosts;
    // the window must NOT close on those or the payment breaks.
    expect(classifyCheckoutNavigation('https://bank.example.com/3ds?txid=1')).toBeNull()
  })

  test('a hostile page cannot forge markers with lookalike params', () => {
    expect(classifyCheckoutNavigation('https://evil.example.com/?checkout=succeeded')).toBeNull()
    expect(classifyCheckoutNavigation('https://evil.example.com/?xcheckout=success')).toBeNull()
  })

  test('returns null for malformed URLs', () => {
    expect(classifyCheckoutNavigation('not a url')).toBeNull()
    expect(classifyCheckoutNavigation('')).toBeNull()
  })
})
