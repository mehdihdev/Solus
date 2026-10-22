// The credit balance for Settings › Plan & usage (SOLUSDEV-318). One read of
// GET /users/me/credits; a failure leaves it unknown (shown as "—"), never 0.
import { useEffect, useState } from 'react'
import { getCredits } from '../../lib/api/resources'

export interface CreditsView {
  balance: number | null
  unlimited: boolean
}

const UNKNOWN: CreditsView = { balance: null, unlimited: false }

export function useCredits(enabled: boolean): CreditsView {
  const [view, setView] = useState<CreditsView>(UNKNOWN)
  useEffect(() => {
    if (!enabled) return
    let active = true
    getCredits().then(
      (c) => {
        if (active) setView({ balance: c.balance, unlimited: c.unlimited === true })
      },
      () => undefined // the Billing page owns the error story; here it just stays "—"
    )
    return () => {
      active = false
    }
  }, [enabled])
  return view
}
