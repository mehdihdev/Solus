// Live billing data for the Billing screen: loads the current subscription and
// exposes a plan-change action (PATCH /users/me/subscription — no Stripe call,
// ADR-032). Degrades to `offline` when the workspace can't reach the API, and
// tolerates a 404 (no subscription yet) as a ready-with-null state. Mirrors the
// fetch-enablement of Home/Team so a signed-in, non-onboarded user still loads.
import { useCallback, useEffect, useState } from 'react'
import {
  getSubscription,
  updateSubscription,
  type PlanType,
  type Subscription
} from '../../lib/api/resources'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

export type BillingStatus = 'loading' | 'ready' | 'offline'

export interface BillingData {
  status: BillingStatus
  subscription: Subscription | null
  /** True while a plan change is in flight (disables the plan controls). */
  changing: boolean
  /** Switch plans; resolves true on success, false on failure (plan unchanged). */
  changePlan: (plan: PlanType) => Promise<boolean>
  refresh: () => Promise<void>
}

export function useBillingData(): BillingData {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const [status, setStatus] = useState<BillingStatus>(fetchEnabled ? 'loading' : 'offline')
  const [subscription, setSubscription] = useState<Subscription | null>(null)
  const [changing, setChanging] = useState(false)

  const load = useCallback(async (): Promise<void> => {
    if (!fetchEnabled) {
      setStatus('offline')
      return
    }
    try {
      setSubscription(await getSubscription())
      setStatus('ready')
    } catch {
      // A 404 (no subscription on the account) is a valid ready state, not an
      // outage — show the empty billing view rather than the offline notice.
      setSubscription(null)
      setStatus('ready')
    }
  }, [fetchEnabled])

  useEffect(() => {
    void load()
  }, [load])

  const changePlan = useCallback(async (plan: PlanType): Promise<boolean> => {
    setChanging(true)
    try {
      setSubscription(await updateSubscription(plan))
      return true
    } catch {
      return false
    } finally {
      setChanging(false)
    }
  }, [])

  return { status, subscription, changing, changePlan, refresh: load }
}
