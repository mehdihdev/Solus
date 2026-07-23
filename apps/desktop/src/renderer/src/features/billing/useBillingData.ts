// Live billing data for the Billing screen. Loads the subscription, credit
// balance, and purchasable packs, and drives the real Stripe flows: subscription
// checkout, credit-pack checkout, and the billing portal all return a hosted URL
// that we open in the system browser (via the preload bridge, window.open
// fallback). On return from that browser tab the window `focus` event refetches
// so the new plan/credits appear. Degrades to `offline` when the workspace can't
// reach the API. (SOLUSDEV-83 follow-up — replaces the trial-only PATCH flow.)
import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../../lib/api/envelope.types'
import {
  createBillingPortal,
  createPackCheckout,
  createSubscriptionCheckout,
  getCreditPacks,
  getCredits,
  getSubscription,
  type CheckoutInterval,
  type CreditPack,
  type PlanType,
  type Subscription
} from '../../lib/api/resources'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

export type BillingStatus = 'loading' | 'ready' | 'offline'

export interface BillingData {
  status: BillingStatus
  subscription: Subscription | null
  /** Credit balance, or null before it has loaded. */
  credits: number | null
  packs: CreditPack[]
  /** True while a checkout/portal action is in flight (disables the controls). */
  busy: boolean
  /** A user-facing message when an action can't proceed (e.g. billing unconfigured). */
  notice: string | null
  clearNotice: () => void
  /** Open Stripe Checkout for a subscription plan (basic/pro) at the given interval. */
  startCheckout: (plan: PlanType, interval: CheckoutInterval) => Promise<void>
  /** Open Stripe Checkout for a one-off credit pack. */
  buyPack: (priceId: string) => Promise<void>
  /** Open the Stripe billing portal (manage payment method / cancel). */
  openPortal: () => Promise<void>
  refresh: () => Promise<void>
}

/** Open a Stripe URL in the system browser: the preload bridge if present
 *  (Electron), else window.open (which the main process also routes external). */
async function openExternal(url: string): Promise<void> {
  const opener = (
    window as unknown as {
      solus?: { billing?: { openExternal?: (u: string) => Promise<{ ok: boolean }> } }
    }
  ).solus?.billing?.openExternal
  if (opener) {
    await opener(url)
    return
  }
  // Fallback (non-Electron / tests): still refuse non-https, matching the main
  // process's guard so both paths enforce the same invariant.
  try {
    if (new URL(url).protocol === 'https:') window.open(url, '_blank', 'noopener,noreferrer')
  } catch {
    /* malformed URL — open nothing */
  }
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'billing_unconfigured')
      return 'Billing isn’t configured yet — add your Stripe keys and prices to enable checkout.'
    if (error.code === 'no_billing_customer')
      return 'Start a subscription first to open the billing portal.'
    if (error.code === 'already_subscribed')
      return 'You already have an active subscription — use “Manage billing” to change plans.'
    if (error.code === 'plan_not_checkoutable')
      return 'That plan isn’t available for self-serve checkout.'
  }
  return 'Something went wrong reaching Stripe. Please try again.'
}

/** Load subscription (404 → null), credit balance, and packs. Credits/packs are
 *  best-effort so a hiccup there never flips the screen offline. */
async function fetchSnapshot(): Promise<{
  subscription: Subscription | null
  credits: number | null
  packs: CreditPack[]
}> {
  let subscription: Subscription | null = null
  try {
    subscription = await getSubscription()
  } catch {
    subscription = null
  }
  let credits: number | null = null
  try {
    credits = (await getCredits()).balance
  } catch {
    credits = null
  }
  let packs: CreditPack[] = []
  try {
    packs = await getCreditPacks()
  } catch {
    packs = []
  }
  return { subscription, credits, packs }
}

export function useBillingData(): BillingData {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const [status, setStatus] = useState<BillingStatus>(fetchEnabled ? 'loading' : 'offline')
  const [subscription, setSubscription] = useState<Subscription | null>(null)
  const [credits, setCredits] = useState<number | null>(null)
  const [packs, setPacks] = useState<CreditPack[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async (): Promise<void> => {
    if (!fetchEnabled) {
      setStatus('offline')
      return
    }
    const snap = await fetchSnapshot()
    setSubscription(snap.subscription)
    if (snap.credits !== null) setCredits(snap.credits)
    setPacks(snap.packs)
    setStatus('ready')
  }, [fetchEnabled])

  useEffect(() => {
    void load()
  }, [load])

  // Returning from the Stripe browser tab refocuses the app — refetch so the new
  // plan/credits show without a manual reload.
  useEffect(() => {
    const onFocus = (): void => void load()
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [load])

  const runAction = useCallback(async (getUrl: () => Promise<string>): Promise<void> => {
    setBusy(true)
    setNotice(null)
    try {
      await openExternal(await getUrl())
    } catch (error) {
      setNotice(messageFor(error))
    } finally {
      setBusy(false)
    }
  }, [])

  const startCheckout = useCallback(
    (plan: PlanType, interval: CheckoutInterval): Promise<void> =>
      runAction(async () => (await createSubscriptionCheckout(plan, interval)).url),
    [runAction]
  )
  const buyPack = useCallback(
    (priceId: string): Promise<void> =>
      runAction(async () => (await createPackCheckout(priceId)).url),
    [runAction]
  )
  const openPortal = useCallback(
    (): Promise<void> => runAction(async () => (await createBillingPortal()).url),
    [runAction]
  )

  return {
    status,
    subscription,
    credits,
    packs,
    busy,
    notice,
    clearNotice: () => setNotice(null),
    startCheckout,
    buyPack,
    openPortal,
    refresh: load
  }
}
