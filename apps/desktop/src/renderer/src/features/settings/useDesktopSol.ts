// The desktop SOL window settings (SOLUSDEV-252 S3) as Settings reads them:
// main-owned ~/.solus/config.json over window.solus.sol. getState on mount,
// then every sol:state push. Lifted out of the SOL section in SOLUSDEV-318 so
// the Needs-attention callout and the SOL rows share one copy.
import { useCallback, useEffect, useState } from 'react'
import type { SolBridge } from '../../lib/desktopBridge'
import type { SolState } from '../../../../main/sol-window/solWindow'

export const SOL_LOAD_ERROR =
  "SOL settings didn't load from the desktop app — reopen Settings to retry."
export const SOL_APPLY_ERROR = "The desktop app didn't accept that change."

export interface DesktopSol {
  /** False in the browser preview: the SOL window rows live in the desktop app. */
  available: boolean
  state: SolState | null
  error: string | null
  /** Run a bridge call and adopt the state it returns (main is the source of truth). */
  apply: (call: (bridge: SolBridge) => Promise<SolState | null>) => void
  /** Open the OS pane that grants screen capture (main picks the URL). */
  openCaptureSettings: () => void
  /** Re-read the state — capture permission is re-probed on every read. */
  recheck: () => void
}

export function useDesktopSol(bridge: SolBridge | null): DesktopSol {
  const [state, setState] = useState<SolState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const adopt = useCallback((next: SolState | null, failure: string): void => {
    if (next) setState(next)
    setError(next ? null : failure)
  }, [])
  // A refused or rejected call reads the same to the user: the plain line below.
  const run = useCallback(
    (p: Promise<SolState | null>, failure: string): void => {
      void p.then(
        (s) => adopt(s, failure),
        () => adopt(null, failure)
      )
    },
    [adopt]
  )
  useEffect(() => {
    if (!bridge) return
    run(bridge.getState(), SOL_LOAD_ERROR)
    return bridge.onState((s) => adopt(s, SOL_LOAD_ERROR))
  }, [bridge, run, adopt])
  const apply = (call: (b: SolBridge) => Promise<SolState | null>): void => {
    if (bridge) run(call(bridge), SOL_APPLY_ERROR)
  }
  return {
    available: bridge !== null,
    state,
    error,
    apply,
    openCaptureSettings: () => apply((b) => b.openCaptureSettings()),
    recheck: () => apply((b) => b.getState())
  }
}
