// Narrow typing of the preload `window.solus.billing` bridge (SOLUSDEV-114,
// SOLUSDEV-236). Every member is optional: absent outside Electron / in tests.
/** How the in-app checkout window ended. */
export type CheckoutStatus = 'success' | 'cancel' | 'return' | 'closed' | 'blocked' | 'busy'

export interface BillingBridge {
  openExternal?: (u: string) => Promise<{ ok: boolean }>
  openCheckout?: (u: string) => Promise<{ status: CheckoutStatus }>
  contactSales?: () => Promise<{ ok: boolean }>
}

export function billingBridge(): BillingBridge | undefined {
  return (window as unknown as { solus?: { billing?: BillingBridge } }).solus?.billing
}

/** Enterprise "Contact sales": main opens a fixed mailto; the renderer passes
 *  no URL or subject. Failure is the OS mail client's to handle. */
export function contactSales(): void {
  const open = billingBridge()?.contactSales
  if (!open) return
  void Promise.resolve(open()).catch(() => undefined)
}
