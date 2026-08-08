// Guard for billing URLs opened in the system browser (SOLUSDEV-83 follow-up).
// Pure + side-effect free so it is unit-testable without booting Electron.

/** True only for an https URL on a Stripe host. The URL comes from our own API,
 *  but constraining scheme + host closes the residual phishing vector if the
 *  renderer is ever compromised (CLAUDE.md §7). */
export function isAllowedBillingUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== 'https:') return false
    return parsed.hostname === 'stripe.com' || parsed.hostname.endsWith('.stripe.com')
  } catch {
    return false
  }
}

/** The Stripe-hosted surfaces our API actually returns URLs for. */
const CHECKOUT_ENTRY_HOSTS = new Set([
  'checkout.stripe.com',
  'billing.stripe.com',
  'pay.stripe.com'
])

/** True only for an https URL on a checkout/portal host. Deliberately narrower
 *  than isAllowedBillingUrl for ENTRY points (the in-app checkout window and
 *  system-browser opens): anyone can mint a buy.stripe.com Payment Link with an
 *  arbitrary post-payment redirect, so `*.stripe.com` is not trustworthy as a
 *  place to send the user to pay (SOLUSDEV-114 sec review M3). */
export function isAllowedCheckoutEntryUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' && CHECKOUT_ENTRY_HOSTS.has(parsed.hostname)
  } catch {
    return false
  }
}
