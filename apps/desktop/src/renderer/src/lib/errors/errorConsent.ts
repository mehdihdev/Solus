// SOLUSDEV-311 (security review M3, human decision): keep main's Sentry gate
// in step with the signed-in user's data-collection consent (ADR-011). Main
// starts closed; this opens it only for a user who consented, and closes it on
// sign-out. A generation counter stops a slow settings fetch from re-opening
// the gate after the user has signed out. Never throws.
import type { DiagnosticsBridge } from '../desktopBridge'

export type AuthStatusLike = 'loading' | 'authenticated' | 'unauthenticated'

export interface ConsentSyncDeps {
  bridge: () => DiagnosticsBridge | null
  fetchConsent: () => Promise<boolean>
}

export interface ConsentSync {
  onAuthStatus: (status: AuthStatusLike) => Promise<void>
  /** Settings saved a new choice. */
  onConsentChanged: (consent: boolean) => void
}

export function createConsentSync(deps: ConsentSyncDeps): ConsentSync {
  let generation = 0
  const send = (consent: boolean): void => {
    void deps.bridge()?.setConsent(consent)
  }
  return {
    async onAuthStatus(status) {
      generation += 1
      if (status === 'unauthenticated') send(false)
      if (status !== 'authenticated' || !deps.bridge()) return
      const mine = generation
      try {
        const consent = await deps.fetchConsent()
        if (mine === generation) send(consent)
      } catch {
        // Unknown consent stays closed.
      }
    },
    onConsentChanged: (consent) => {
      // A saved choice outranks any sign-in fetch still in flight.
      generation += 1
      send(consent)
    }
  }
}
