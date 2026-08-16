// Provider-agnostic OAuth connect orchestration (SOLUSDEV-103, generalised from
// the GitHub-only flow). Wires the Electron loopback OAuth bridge to the backend
// connector: start OAuth for a PROVIDER → capture the callback → exchange for a
// source → run the provider's configure step → sync → poll to completion.
//
// The provider is an argument at every layer, so a new OAuth connector needs no
// change here. What differs per provider — which repo/document/ids the source
// needs before it can sync — is injected as a `ConfigureStep`, never branched on
// a provider id. All transport + bridge access is injected so this is unit
// testable without React or Electron.
import type { OAuthStartResponse, Source, Sync } from '../../lib/api/resources'
import type { OAuthBridge } from '../auth/githubOAuth'
import type { AccessChoiceStep } from './accessChoiceStep'
import type { ConnectionState, ConnectStage } from './onboardingStore'
import { pollSync, syncErrorMessage } from './sourceSync'

/** The slice of the typed API surface this orchestration depends on. */
export interface OAuthConnectApi {
  startOAuth: (
    projectId: string,
    provider: string,
    input: { redirect_uri?: string; name?: string; access?: string }
  ) => Promise<OAuthStartResponse>
  exchangeOAuth: (provider: string, input: { state: string; code: string }) => Promise<Source>
  updateSource: (
    projectId: string,
    sourceId: string,
    input: { name?: string; config?: Record<string, unknown> }
  ) => Promise<Source>
  triggerSync: (projectId: string, sourceId: string) => Promise<{ job_id: string; status: string }>
  getSyncs: (projectId: string, sourceId: string) => Promise<Sync[]>
  getSource: (projectId: string, sourceId: string) => Promise<Source>
}

/** What a configure step is given: the freshly connected, unconfigured source. */
export interface ConfigureContext {
  projectId: string
  sourceId: string
  provider: string
}

/**
 * The outcome of a provider's post-auth configuration: the config to write onto
 * the source (plus an optional label for progress copy), or an honest error when
 * the user cancelled or there was nothing to choose. The step owns its own copy
 * — the spine never invents a reason on its behalf.
 */
export type ConfigureOutcome =
  | { config: Record<string, unknown>; label?: string }
  | { error: string }

export type ConfigureStep = (ctx: ConfigureContext) => Promise<ConfigureOutcome>

export interface OAuthConnectDeps {
  api: OAuthConnectApi
  bridge: OAuthBridge | null
  /** Push live connection state into the store. */
  onProgress: (state: ConnectionState) => void
  /** Provider-specific post-auth configuration (repo pick, id form, …). */
  configure: ConfigureStep
  /** How much power the user grants, chosen BEFORE authorization. Optional so
   *  callers with nothing to ask keep working unchanged. */
  chooseAccess?: AccessChoiceStep
  /** Optional sleep override so tests don't actually wait between poll ticks. */
  sleep?: (ms: number) => Promise<void>
}

export interface OAuthConnectOptions {
  /** Loopback redirect URL minted by main (carries its own csrf nonce). */
  redirectUri: string
  /** Human name for progress copy ("Onshape"); falls back to the provider id. */
  displayName?: string
}

export interface OAuthConnectResult {
  ok: boolean
  sourceId?: string
  result?: string
  error?: string
}

/** The bridge is an Electron capability — absent in a plain browser context. */
export function noBridgeError(displayName: string): string {
  return `${displayName} connect needs the desktop app.`
}

function busy(stage: ConnectStage, label: string, sourceId?: string): ConnectionState {
  return { phase: 'busy', stage, label, sourceId }
}

/**
 * Drive a full real OAuth connect for `provider`. Reports progress through
 * `onProgress`; returns a structured result. Never throws — failures resolve to
 * `{ ok: false, error }` so the caller can mark the tile errored.
 */
export async function runOAuthConnect(
  deps: OAuthConnectDeps,
  projectId: string,
  provider: string,
  options: OAuthConnectOptions
): Promise<OAuthConnectResult> {
  const label = options.displayName ?? provider

  if (!deps.bridge) {
    const error = noBridgeError(label)
    deps.onProgress({ phase: 'error', error })
    return { ok: false, error }
  }

  try {
    const authorized = await authorize(deps, deps.bridge, projectId, provider, options, label)
    if ('error' in authorized) {
      deps.onProgress({ phase: 'error', error: authorized.error, sourceId: authorized.sourceId })
      return { ok: false, error: authorized.error, sourceId: authorized.sourceId }
    }

    deps.onProgress(busy('link', `Linking your ${label} account…`, authorized.sourceId))
    const source = await deps.api.exchangeOAuth(provider, {
      state: authorized.state,
      code: authorized.code
    })

    const outcome = await deps.configure({ projectId, sourceId: source.id, provider })
    if ('error' in outcome) {
      deps.onProgress({ phase: 'error', error: outcome.error, sourceId: source.id })
      return { ok: false, error: outcome.error, sourceId: source.id }
    }

    return await indexSource(deps, projectId, source.id, outcome, label)
  } catch (error) {
    const message = error instanceof Error ? error.message : `${label} connect failed.`
    deps.onProgress({ phase: 'error', error: message })
    return { ok: false, error: message }
  }
}

type Authorized =
  | { state: string; code: string; sourceId: string }
  | { error: string; sourceId?: string }

/**
 * Everything up to and including the provider handshake: choose the grant, mint
 * the authorize URL, wait for the loopback callback.
 *
 * The grant choice comes FIRST because it decides the scopes IN the authorize
 * URL — it cannot be a post-auth step like `configure` (SOLUS-ONS-A2).
 */
async function authorize(
  deps: OAuthConnectDeps,
  bridge: OAuthBridge,
  projectId: string,
  provider: string,
  options: OAuthConnectOptions,
  label: string
): Promise<Authorized> {
  const access = deps.chooseAccess ? await deps.chooseAccess() : { access: undefined }
  if ('error' in access) return { error: access.error }

  deps.onProgress(busy('authorize', `Authorizing with ${label}…`))
  const start = await deps.api.startOAuth(projectId, provider, {
    redirect_uri: options.redirectUri,
    ...(access.access ? { access: access.access } : {})
  })

  // Match the callback on the backend's own OAuth state, which the provider
  // echoes back — the connector redirect URL carries no nonce of its own so
  // that strict providers (Onshape) can match it exactly.
  const callback = await bridge.awaitOAuth(start.authorize_url, start.state)
  if (callback.error) return { error: callback.error, sourceId: start.source_id }
  if (!callback.code) {
    return { error: `${label} sign-in was cancelled.`, sourceId: start.source_id }
  }
  return { state: start.state, code: callback.code, sourceId: start.source_id }
}

/** Write the chosen config onto the source, sync, poll, and report the result. */
async function indexSource(
  deps: OAuthConnectDeps,
  projectId: string,
  sourceId: string,
  outcome: { config: Record<string, unknown>; label?: string },
  displayName: string
): Promise<OAuthConnectResult> {
  deps.onProgress(busy('index', `Indexing ${outcome.label ?? displayName}…`, sourceId))
  await deps.api.updateSource(projectId, sourceId, { config: outcome.config })
  await deps.api.triggerSync(projectId, sourceId)

  const sync = await pollSync(deps.api, projectId, sourceId, deps.sleep)
  if (!sync) {
    const error = 'Sync timed out.'
    deps.onProgress({ phase: 'error', error, sourceId })
    return { ok: false, error, sourceId }
  }
  if (sync.status === 'failed') {
    const error = syncErrorMessage(sync)
    deps.onProgress({ phase: 'error', error, sourceId })
    return { ok: false, error, sourceId }
  }

  const source = await deps.api.getSource(projectId, sourceId)
  const count = source.entity_count ?? sync.entities_created
  const result = `Connected — ${count} entities indexed`
  deps.onProgress({ phase: 'done', sourceId, result })
  return { ok: true, sourceId, result }
}
