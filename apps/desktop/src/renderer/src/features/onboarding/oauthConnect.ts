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
import type { OAuthExchangeResult, OAuthStartResponse, Source, Sync } from '../../lib/api/resources'
import type { OAuthBridge } from '../auth/githubOAuth'
import type { AccessChoiceStep } from './accessChoiceStep'
import type { AddOnStep } from './addOnStep'
import type { ConnectionState, ConnectStage } from './onboardingStore'
import { pollAcceptedSync, indexedSyncDetail, type SyncJobApi } from './sourceSync'

/** The slice of the typed API surface this orchestration depends on. */
export interface OAuthConnectApi extends SyncJobApi {
  startOAuth: (
    projectId: string,
    provider: string,
    input: { redirect_uri?: string; name?: string; access?: string }
  ) => Promise<OAuthStartResponse>
  exchangeOAuth: (
    provider: string,
    input: { state: string; code: string }
  ) => Promise<OAuthExchangeResult>
  /** SOLUSDEV-241: attach the project to an account the user already linked
   *  on Home — no browser handshake. */
  createSource: (
    projectId: string,
    input: { type: string; name: string; connection_id: string }
  ) => Promise<Source>
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
  /** A vendor-hosted add-on enabled as part of this connect (SOLUSDEV-168:
   *  "one connect, FeatureScript comes with it"). Optional, and it can never
   *  fail the connection. */
  addOn?: AddOnStep
  /** Optional sleep override so tests don't actually wait between poll ticks. */
  sleep?: (ms: number) => Promise<void>
}

export interface OAuthConnectOptions {
  /** Loopback redirect URL minted by main (carries its own csrf nonce). */
  redirectUri: string
  /** Human name for progress copy ("Onshape"); falls back to the provider id. */
  displayName?: string
  /** SOLUSDEV-241: a linked account to reuse. Present, the grant choice and the
   *  sign-in are skipped — asking again would be asking for something the user
   *  already gave — and the project is bound to it directly. */
  linkedConnection?: { id: string; login: string | null } | null
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

  try {
    const linked = await link(deps, deps.bridge, projectId, provider, options, label)
    if ('error' in linked) {
      deps.onProgress({ phase: 'error', error: linked.error, sourceId: linked.sourceId })
      return { ok: false, error: linked.error, sourceId: linked.sourceId }
    }
    const source = linked.source

    // HERE, and not on a button afterwards. The account exists as of the line
    // above, the browser still holds the vendor session from the handshake that
    // just finished, and the loopback has settled — so the add-on's own sign-in
    // is usually a redirect the user barely sees. It cannot fail this connect.
    const addOnNote = deps.addOn ? await deps.addOn({ projectId, sourceId: source.id }) : null

    const outcome = await deps.configure({ projectId, sourceId: source.id, provider })
    if ('error' in outcome) {
      deps.onProgress({ phase: 'error', error: outcome.error, sourceId: source.id })
      return { ok: false, error: outcome.error, sourceId: source.id }
    }

    return await indexSource(deps, projectId, source.id, outcome, label, addOnNote)
  } catch (error) {
    const message = error instanceof Error ? error.message : `${label} connect failed.`
    deps.onProgress({ phase: 'error', error: message })
    return { ok: false, error: message }
  }
}

type Authorized =
  | { state: string; code: string; sourceId?: string }
  | { error: string; sourceId?: string }

type Linked = { source: Source } | { error: string; sourceId?: string }

/**
 * Get the project a CONNECTED source: bind it to a linked account when one is
 * offered (SOLUSDEV-241 — no handshake), otherwise authorize + exchange.
 */
async function link(
  deps: OAuthConnectDeps,
  bridge: OAuthBridge | null,
  projectId: string,
  provider: string,
  options: OAuthConnectOptions,
  label: string
): Promise<Linked> {
  if (options.linkedConnection) {
    deps.onProgress(busy('link', `Using your linked ${label} account…`))
    const source = await deps.api.createSource(projectId, {
      type: provider,
      name: label,
      connection_id: options.linkedConnection.id
    })
    return { source }
  }
  if (!bridge) return { error: noBridgeError(label) }
  const authorized = await authorize(deps, bridge, projectId, provider, options, label)
  if ('error' in authorized) return authorized

  deps.onProgress(busy('link', `Linking your ${label} account…`, authorized.sourceId))
  const exchanged = await deps.api.exchangeOAuth(provider, {
    state: authorized.state,
    code: authorized.code
  })
  if (!exchanged.source) {
    // The grant landed on the account but nothing attached it to this project
    // — a server contract breach, reported rather than papered over.
    return {
      error: `${label} was linked to your account but not to this project.`,
      sourceId: authorized.sourceId
    }
  }
  return { source: exchanged.source }
}

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
  const sourceId = start.source_id ?? undefined
  const callback = await bridge.awaitOAuth(start.authorize_url, start.state)
  if (callback.error) return { error: callback.error, sourceId }
  if (!callback.code) {
    return { error: `${label} sign-in was cancelled.`, sourceId }
  }
  return { state: start.state, code: callback.code, sourceId }
}

/** Write the chosen config onto the source, sync, poll, and report the result. */
async function indexSource(
  deps: OAuthConnectDeps,
  projectId: string,
  sourceId: string,
  outcome: { config: Record<string, unknown>; label?: string },
  displayName: string,
  addOnNote: string | null = null
): Promise<OAuthConnectResult> {
  deps.onProgress(busy('index', `Indexing ${outcome.label ?? displayName}…`, sourceId))
  await deps.api.updateSource(projectId, sourceId, { config: outcome.config })
  const accepted = await deps.api.triggerSync(projectId, sourceId)

  const job = await pollAcceptedSync(deps.api, projectId, accepted.job_id, deps.sleep)
  if (!job) {
    const error = 'Sync timed out.'
    deps.onProgress({ phase: 'error', error, sourceId })
    return { ok: false, error, sourceId }
  }
  if (job.status !== 'succeeded') {
    const error =
      job.error?.message ?? (job.status === 'cancelled' ? 'Sync cancelled.' : 'Sync failed.')
    deps.onProgress({ phase: 'error', error, sourceId })
    return { ok: false, error, sourceId }
  }

  const source = await deps.api.getSource(projectId, sourceId)
  const detail = await indexedSyncDetail(deps.api, projectId, sourceId, source.entity_count)
  // The add-on note rides the REAL result string rather than replacing it: a
  // connect that indexed nothing has not become a success because an extra
  // turned on, and the entity count is what the person came for.
  const result = `Connected — ${detail}${addOnNote ? ` · ${addOnNote}` : ''}`
  deps.onProgress({ phase: 'done', sourceId, result })
  return { ok: true, sourceId, result }
}
