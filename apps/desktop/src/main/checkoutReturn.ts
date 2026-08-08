// Classifier for top-frame navigation inside the in-app checkout window
// (SOLUSDEV-114). Pure + side-effect free so it is unit-testable without
// booting Electron (same pattern as billingUrl.ts / oauthCallback.ts).

export type CheckoutNavigation = 'success' | 'cancel' | 'return' | null

/** Extract query params from both the real query string and the query embedded
 *  in a hash-router fragment (`/#/billing?checkout=success`). */
function markerParams(parsed: URL): URLSearchParams {
  const merged = new URLSearchParams(parsed.searchParams)
  const hashQuery = parsed.hash.split('?')[1]
  if (hashQuery) {
    for (const [key, value] of new URLSearchParams(hashQuery)) merged.append(key, value)
  }
  return merged
}

/** Classify a navigation target by our configured return-URL markers:
 *  `checkout=success|cancel` (Checkout) and `portal=return` (billing portal).
 *  Anything else — including 3DS/bank-auth hops through non-Stripe hosts —
 *  returns null and must NOT close the window. A forged marker URL can only
 *  close the window early; entitlement always comes from the signed webhook. */
export function classifyCheckoutNavigation(url: string): CheckoutNavigation {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return null
  }
  const params = markerParams(parsed)
  const checkout = params.get('checkout')
  if (checkout === 'success') return 'success'
  if (checkout === 'cancel') return 'cancel'
  if (params.get('portal') === 'return') return 'return'
  return null
}
