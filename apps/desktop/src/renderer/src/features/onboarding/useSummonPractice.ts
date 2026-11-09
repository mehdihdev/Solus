// SOLUSDEV-323: the Access step's "try it now" — listens for main's REAL
// hotkey-summon push (sol:summoned) and counts summons, so the key caps can
// replay their press per summon. Unsubscribes on unmount.
import { useEffect, useState } from 'react'
import type { SolBridge } from '../../lib/desktopBridge'

export interface SummonPractice {
  /** How many real summons happened while the step was open. */
  summons: number
}

export function useSummonPractice(bridge: SolBridge | null): SummonPractice {
  const [summons, setSummons] = useState(0)
  useEffect(() => {
    if (!bridge) return
    return bridge.onSummoned(() => setSummons((n) => n + 1))
  }, [bridge])
  return { summons }
}
