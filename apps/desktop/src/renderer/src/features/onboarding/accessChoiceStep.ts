// The connect-time grant choice (SOLUS-ONS-A2), the step BEFORE authorization.
//
// Editing CAD is the product, so the capability is offered rather than withheld
// — but Onshape grants are ACCOUNT-WIDE (there is no per-document or per-project
// scope), so the customer decides how much power Solus gets while connecting,
// and every edit still passes the per-action confirmation gate afterwards.
//
// GENERIC by construction: the modes come from the connector's own
// `access_modes` in the live registry, exactly like `selection`. Fusion,
// SolidWorks and AutoCAD declare their own and land with no change here.
import type { IntegrationAccessModes } from '../../lib/api/resources'
import type { ConnectionState } from './onboardingStore'

/** Chosen mode id, or an honest error. `access: undefined` = no choice offered. */
export type AccessOutcome = { access: string | undefined } | { error: string }

export type AccessChoiceStep = () => Promise<AccessOutcome>

export interface AccessChoiceDeps {
  accessModes: IntegrationAccessModes | null | undefined
  /** Push live connection state into the store (surfaces the choice). */
  onProgress: (state: ConnectionState) => void
  /** Resolve the in-tile choice: a mode id, or null to cancel. */
  onChoose: (modes: IntegrationAccessModes) => Promise<string | null>
}

/** Distinct from fieldsConfigureStep's CANCELLED_ERROR: this one aborts BEFORE
 *  authorization, so nothing was granted and no source was configured. */
export const ACCESS_CANCELLED_ERROR = 'Connect cancelled.'

export function accessChoiceStep(deps: AccessChoiceDeps): AccessChoiceStep {
  return async (): Promise<AccessOutcome> => {
    const offered = deps.accessModes
    if (!offered || offered.modes.length === 0) return { access: undefined }
    // Nothing to decide — sending the only mode is still explicit.
    if (offered.modes.length === 1) return { access: offered.modes[0].id }

    deps.onProgress({
      phase: 'busy',
      stage: 'access',
      label: 'How much access should Solus have?',
      accessModes: offered
    })
    const chosen = await deps.onChoose(offered)
    // An unoffered id can only come from a bug or a tampered payload; refusing
    // beats defaulting, because the default a caller would reach for here is the
    // WIDER grant, and that is exactly what must never happen implicitly.
    if (chosen === null || !offered.modes.some((mode) => mode.id === chosen)) {
      return { error: ACCESS_CANCELLED_ERROR }
    }
    return { access: chosen }
  }
}
