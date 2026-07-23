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
