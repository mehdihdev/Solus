// Live billing data for the Billing screen. Loads the subscription, credit
// balance, and purchasable packs, and drives the real Stripe flows: subscription
// checkout, credit-pack checkout, and the billing portal all return a hosted URL
// that we open in the system browser (via the preload bridge, window.open
// fallback). On return from that browser tab the window `focus` event refetches
// so the new plan/credits appear. Degrades to `offline` when the workspace can't
// reach the API. (SOLUSDEV-83 follow-up — replaces the trial-only PATCH flow.)
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../../lib/api/envelope.types'
import {
  createPackCheckout,
  createSubscriptionCheckout,
  getCreditPacks,
  getCredits,
  type CheckoutInterval,
  type CreditPack,
  type PlanType
} from '../../lib/api/resources'
import {
  createBillingPortalFlow,
  getBillingSubscription,
  getBillingSummary,
  type BillingSubscription,
  type BillingSummary,
  type PortalFlow
} from '../../lib/api/resources.billing'
import { billingBridge, type CheckoutStatus } from './billingBridge'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

export type BillingStatus = 'loading' | 'ready' | 'offline'

export interface BillingData {
  status: BillingStatus
  subscription: BillingSubscription | null
  /** GET /billing/summary; null when it failed (the page then degrades to
   *  "Stripe unavailable" locally — the page itself stays online). */
  summary: BillingSummary | null
  /** When the snapshot was taken (ms); the clock for read-time trial expiry. */
  asOf: number
  /** Credit balance, or null before it has loaded. */
  credits: number | null
  unlimited: boolean
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
  /** Open the portal, deep-linked to plan change (`update`) or cancel (`cancel`). */
  openPortalFlow: (flow?: PortalFlow) => Promise<void>
  refresh: () => Promise<void>
}

/** Dispatched after a checkout completes so the shell bell refetches and shows
 *  the webhook's payment notification without waiting for a remount. */
export const NOTIFICATIONS_REFRESH_EVENT = 'solus:notifications-refresh'

/** The webhook applies the entitlement moments after Stripe confirms payment —
 *  refetch a few times after the checkout window closes to absorb that lag. */
const POST_CHECKOUT_REFRESH_DELAYS_MS = [1500, 4000, 10000] as const

const SUCCESS_NOTICE = 'Payment received — your plan and credits are updating now.'
const CANCELED_NOTICE = 'Checkout canceled — you haven’t been charged.'

/** Which action failed, so the generic copy names it (wireflow §Actions). */
type ActionKind = 'checkout' | 'portal'

/** Open a Stripe URL in the system browser: the preload bridge if present
 *  (Electron), else window.open (which the main process also routes external). */
async function openExternal(url: string): Promise<void> {
  const opener = billingBridge()?.openExternal
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

const UNAVAILABLE_NOTICE =
  'Billing is temporarily unavailable — your plan is unchanged. Try again in a few minutes.'

const CODE_NOTICES: Record<string, string> = {
  billing_unconfigured:
    'Billing isn’t configured yet — add your Stripe keys and prices to enable checkout.',
  no_billing_customer: 'Start a subscription first to open the billing portal.',
  no_active_subscription: 'This plan can’t be changed right now — use Manage billing.',
  cancel_already_scheduled: 'Your plan is already scheduled to end.',
  already_subscribed:
    'You already have an active subscription — use “Manage billing” to change plans.',
  plan_not_checkoutable: 'That plan isn’t available for self-serve checkout.'
}

function messageFor(error: unknown, kind: ActionKind): string {
  if (error instanceof ApiError) {
    const byCode = CODE_NOTICES[error.code]
    if (byCode) return byCode
    if (error.status === 502 || error.status === 503) return UNAVAILABLE_NOTICE
  }
  return kind === 'checkout'
    ? 'Couldn’t open checkout — try again.'
    : 'Couldn’t open billing — try again.'
}

interface Snapshot {
  subscription: BillingSubscription | null
  summary: BillingSummary | null
  credits: number | null
  unlimited: boolean
  packs: CreditPack[]
}

/** Resolve to `fallback` instead of throwing: every read except the screen's
 *  own offline gate is best-effort so a hiccup never flips the page offline. */
async function orElse<T>(read: Promise<T>, fallback: T): Promise<T> {
  try {
    return await read
  } catch {
    return fallback
  }
}

/** Load subscription (404 → null), summary (failure → null = degraded), credit
 *  balance, and packs, concurrently. */
async function fetchSnapshot(): Promise<Snapshot> {
  const [subscription, summary, balance, packs] = await Promise.all([
    orElse(getBillingSubscription(), null),
    orElse(getBillingSummary(), null),
    orElse(getCredits(), null),
    orElse(getCreditPacks(), [])
  ])
  return {
    subscription,
    summary,
    credits: balance ? balance.balance : null,
    unlimited: balance?.unlimited === true,
    packs
  }
}

export function useBillingData(): BillingData {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const [status, setStatus] = useState<BillingStatus>(fetchEnabled ? 'loading' : 'offline')
  const [subscription, setSubscription] = useState<BillingSubscription | null>(null)
  const [asOf, setAsOf] = useState(0)
  const [summary, setSummary] = useState<BillingSummary | null>(null)
  const [credits, setCredits] = useState<number | null>(null)
  const [unlimited, setUnlimited] = useState(false)
  const [packs, setPacks] = useState<CreditPack[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async (): Promise<void> => {
    if (!fetchEnabled) {
      setUnlimited(false)
      setStatus('offline')
      return
    }
    const snap = await fetchSnapshot()
    setUnlimited(snap.unlimited)
    setSubscription(snap.subscription)
    setSummary(snap.summary)
    setAsOf(Date.now())
    if (snap.credits !== null) setCredits(snap.credits)
    setPacks(snap.packs)
    setStatus('ready')
  }, [fetchEnabled])

  const { finishCheckout, scheduleRefetch } = useCheckoutCompletion(load, setNotice)

  const runAction = useCallback(
    async (kind: ActionKind, getUrl: () => Promise<string>): Promise<void> => {
      setBusy(true)
      setNotice(null)
      try {
        const url = await getUrl()
        const openCheckout = billingBridge()?.openCheckout
        if (openCheckout) {
          // Self-contained: a sandboxed in-app window; busy until it closes.
          finishCheckout((await openCheckout(url)).status, kind)
        } else {
          await openExternal(url)
          scheduleRefetch()
        }
      } catch (error) {
        setNotice(messageFor(error, kind))
        if (error instanceof ApiError && error.code === 'cancel_already_scheduled') void load()
      } finally {
        setBusy(false)
      }
    },
    [finishCheckout, scheduleRefetch, load]
  )

  const startCheckout = useCallback(
    (plan: PlanType, interval: CheckoutInterval): Promise<void> =>
      runAction('checkout', async () => (await createSubscriptionCheckout(plan, interval)).url),
    [runAction]
  )
  const buyPack = useCallback(
    (priceId: string): Promise<void> =>
      runAction('checkout', async () => (await createPackCheckout(priceId)).url),
    [runAction]
  )
  const openPortalFlow = useCallback(
    (flow?: PortalFlow): Promise<void> =>
      runAction('portal', async () => (await createBillingPortalFlow(flow)).url),
    [runAction]
  )
  const openPortal = useCallback((): Promise<void> => openPortalFlow(), [openPortalFlow])

  return {
    status,
    subscription,
    summary,
    asOf,
    credits,
    unlimited,
    packs,
    busy,
    notice,
    clearNotice: () => setNotice(null),
    startCheckout,
    buyPack,
    openPortal,
    openPortalFlow,
    refresh: load
  }
}

interface CheckoutCompletion {
  finishCheckout: (status: CheckoutStatus, kind: ActionKind) => void
  /** Refetch now-ish and again at 1.5/4/10 s (webhook lag) after any open. */
  scheduleRefetch: () => void
}

function useCheckoutCompletion(
  load: () => Promise<void>,
  setNotice: (notice: string | null) => void
): CheckoutCompletion {
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

  // Follow-up refetch timers (post-checkout webhook lag); cleared on unmount.
  const refreshTimersRef = useRef<number[]>([])
  useEffect(() => {
    const timers = refreshTimersRef
    return () => timers.current.forEach((id) => window.clearTimeout(id))
  }, [])

  const refetchEverything = useCallback((): void => {
    void load()
    // Nudge the shell bell so the webhook's payment notification shows up
    // without a remount.
    window.dispatchEvent(new Event(NOTIFICATIONS_REFRESH_EVENT))
  }, [load])

  const scheduleRefetch = useCallback((): void => {
    for (const delay of POST_CHECKOUT_REFRESH_DELAYS_MS) {
      const id = window.setTimeout(() => {
        // Prune fired timers so the list doesn't grow for the app's lifetime.
        refreshTimersRef.current = refreshTimersRef.current.filter((t) => t !== id)
        refetchEverything()
      }, delay)
      refreshTimersRef.current.push(id)
    }
  }, [refetchEverything])

  /** Apply the outcome of the in-app checkout window (SOLUSDEV-114). */
  const finishCheckout = useCallback(
    (status: CheckoutStatus, kind: ActionKind): void => {
      if (status === 'cancel' || status === 'closed') {
        setNotice(CANCELED_NOTICE)
        return
      }
      if (status === 'busy') {
        setNotice('A checkout window is already open — finish or close it first.')
        return
      }
      if (status === 'blocked') {
        setNotice(messageFor(null, kind))
        return
      }
      if (status === 'success') setNotice(SUCCESS_NOTICE)
      refetchEverything()
      scheduleRefetch()
    },
    [refetchEverything, scheduleRefetch, setNotice]
  )

  return { finishCheckout, scheduleRefetch }
}
