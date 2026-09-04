// Enabling a vendor-hosted add-on as PART OF the connection (SOLUSDEV-168).
//
// The brief was "one connect, FeatureScript comes with it" — not a second
// button on a source that is already connected. So this runs inside
// `runOAuthConnect`, immediately after the account is linked, while the user is
// still in the flow and still signed in to the vendor in their browser (which
// usually makes the second handshake a redirect they barely see).
//
// It can NEVER fail the connection. Enabling an add-on is a bonus on top of a
// connector that works without it, and the vendor may simply not have sold the
// customer the app yet — a failure there must not cost them their Onshape
// source. Whatever happens, the durable state lands on the source and the
// Sources page renders the recovery path (subscribe / check again / retry).
import type { ConnectionState } from './onboardingStore'
import type { IntegrationHosted } from '../../lib/api/resources'
import type { OAuthBridge } from '../auth/githubOAuth'

export interface AddOnContext {
  projectId: string
  sourceId: string
}

/** Runs after the account is linked. Resolves to a note for the done copy, or
 *  null when there was nothing to enable or it did not work out. */
export type AddOnStep = (ctx: AddOnContext) => Promise<string | null>

export interface AddOnApi {
  startHostedOAuth: (
    projectId: string,
    sourceId: string,
    server: string
  ) => Promise<{ authorize_url: string; state: string }>
  exchangeHostedOAuth: (
    projectId: string,
    sourceId: string,
    server: string,
    body: { state: string; code: string }
  ) => Promise<{ state: string }>
}

export interface AddOnStepDeps {
  /** The add-on this connector carries, straight from the live registry. Null
   *  for a connector with none — then this step is a no-op. */
  hosted: IntegrationHosted | null
  bridge: OAuthBridge | null
  api: AddOnApi
  onProgress: (state: ConnectionState) => void
  /** True once the wizard was closed: stop rather than opening a browser for a
   *  flow nobody is watching. */
  isCancelled: () => boolean
}

export function addOnStep(deps: AddOnStepDeps): AddOnStep {
  return async ({ projectId, sourceId }) => {
    const { hosted, bridge } = deps
    if (!hosted || !bridge || deps.isCancelled()) return null

    // Same stage as the account link — this IS part of linking the account, and
    // inventing a rail step for something that may legitimately not happen
    // would make the flow look like it went wrong when it did not.
    deps.onProgress({
      phase: 'busy',
      stage: 'link',
      label: `Enabling ${hosted.display_name}…`,
      sourceId
    })

    try {
      const start = await deps.api.startHostedOAuth(projectId, sourceId, hosted.server)
      if (deps.isCancelled()) return null
      const callback = await bridge.awaitOAuth(start.authorize_url, start.state)
      if (deps.isCancelled() || callback.error || !callback.code) return null

      const status = await deps.api.exchangeHostedOAuth(projectId, sourceId, hosted.server, {
        state: start.state,
        code: callback.code
      })
      return status.state === 'ready' ? `${hosted.display_name} enabled` : null
    } catch {
      // Swallowed on purpose. The connection itself succeeded, the state is
      // recorded on the source, and the Sources page is where a user picks this
      // back up — erroring here would throw away a working connector because an
      // optional extra did not land.
      return null
    }
  }
}
