// Real GitHub connect orchestration for onboarding (SOLUSDEV-103). Wires the
// Electron loopback OAuth bridge to the backend connector: start OAuth →
// capture the callback → exchange for a source → pick a repo → sync → poll to
// completion. All transport + bridge access is injected so this is unit-testable
// without React or Electron. The renderer reports progress through `onProgress`
// and resolves the repo choice through `onChooseRepo`.
import type { GithubRepo, OAuthStartResponse, Source, Sync } from '../../lib/api/resources'
import type { OAuthBridge } from '../auth/githubOAuth'
import type { ConnectionState } from './onboardingStore'
import { pollSync, syncErrorMessage } from './sourceSync'

/** The slice of the typed API surface this orchestration depends on. */
export interface GithubConnectApi {
  startGithubOAuth: (
    projectId: string,
    input: { redirect_uri?: string; repo?: string; name?: string }
  ) => Promise<OAuthStartResponse>
  exchangeGithubOAuth: (input: { state: string; code: string }) => Promise<Source>
  listRepos: (projectId: string, sourceId: string) => Promise<GithubRepo[]>
  updateSource: (
    projectId: string,
    sourceId: string,
    input: { name?: string; config?: Record<string, unknown> }
  ) => Promise<Source>
  triggerSync: (projectId: string, sourceId: string) => Promise<{ job_id: string; status: string }>
  getSyncs: (projectId: string, sourceId: string) => Promise<Sync[]>
  getSource: (projectId: string, sourceId: string) => Promise<Source>
}

export interface GithubConnectDeps {
  api: GithubConnectApi
  bridge: OAuthBridge | null
  /** Push live connection state into the store. */
  onProgress: (state: ConnectionState) => void
  /**
   * Resolve which repo to index. Receives the discovered repos; returns the
   * chosen one (or null to cancel). The UI shows a picker; tests pass a stub.
   * Skipped when a repo was preselected.
   */
  onChooseRepo: (repos: GithubRepo[]) => Promise<GithubRepo | null>
  /** Optional sleep override so tests don't actually wait between poll ticks. */
  sleep?: (ms: number) => Promise<void>
}

export interface GithubConnectOptions {
  /** Loopback redirect URL minted by main (carries its own csrf nonce). */
  redirectUri: string
  /** Skip the picker and index this repo directly. */
  preselectedRepo?: GithubRepo
}

export interface GithubConnectResult {
  ok: boolean
  sourceId?: string
  result?: string
  error?: string
}

const NO_BRIDGE_ERROR = 'GitHub connect needs the desktop app.'

function busy(label: string, sourceId?: string, repos?: GithubRepo[]): ConnectionState {
  return { phase: 'busy', stepIdx: 0, label, sourceId, repos }
}

/**
 * Drive the full real-GitHub connect. Reports progress through `onProgress`;
 * returns a structured result. Never throws — failures resolve to
 * `{ ok: false, error }` so the caller can mark the tile errored.
 */
export async function runGithubConnect(
  deps: GithubConnectDeps,
  projectId: string,
  options: GithubConnectOptions
): Promise<GithubConnectResult> {
  if (!deps.bridge) {
    deps.onProgress({ phase: 'error', error: NO_BRIDGE_ERROR })
    return { ok: false, error: NO_BRIDGE_ERROR }
  }

  try {
    deps.onProgress(busy('Authorizing with GitHub…'))
    const start = await deps.api.startGithubOAuth(projectId, {
      redirect_uri: options.redirectUri,
      repo: options.preselectedRepo?.full_name
    })

    const callback = await deps.bridge.awaitGithub(start.authorize_url)
    if (callback.error) {
      deps.onProgress({ phase: 'error', error: callback.error, sourceId: start.source_id })
      return { ok: false, error: callback.error, sourceId: start.source_id }
    }
    if (!callback.code) {
      const error = 'GitHub sign-in was cancelled.'
      deps.onProgress({ phase: 'error', error, sourceId: start.source_id })
      return { ok: false, error, sourceId: start.source_id }
    }

    deps.onProgress(busy('Linking your GitHub account…', start.source_id))
    const source = await deps.api.exchangeGithubOAuth({ state: start.state, code: callback.code })

    const repo = await resolveRepo(deps, projectId, source.id, options.preselectedRepo)
    if (!repo) {
      const error = 'No repository selected.'
      deps.onProgress({ phase: 'error', error, sourceId: source.id })
      return { ok: false, error, sourceId: source.id }
    }

    return await indexRepo(deps, projectId, source.id, repo)
  } catch (error) {
    const message = error instanceof Error ? error.message : 'GitHub connect failed.'
    deps.onProgress({ phase: 'error', error: message })
    return { ok: false, error: message }
  }
}

/** Pick the repo: preselected → use it; otherwise list + ask the UI. */
async function resolveRepo(
  deps: GithubConnectDeps,
  projectId: string,
  sourceId: string,
  preselected?: GithubRepo
): Promise<GithubRepo | null> {
  if (preselected) return preselected
  deps.onProgress(busy('Discovering repositories…', sourceId))
  const repos = await deps.api.listRepos(projectId, sourceId)
  if (repos.length === 0) return null
  if (repos.length === 1) return repos[0]
  // Surface the picker through the store, then await the user's choice.
  deps.onProgress(busy('Choose a repository to index…', sourceId, repos))
  return deps.onChooseRepo(repos)
}

/** Configure the source to the chosen repo, sync, poll, and report the result. */
async function indexRepo(
  deps: GithubConnectDeps,
  projectId: string,
  sourceId: string,
  repo: GithubRepo
): Promise<GithubConnectResult> {
  deps.onProgress(busy(`Indexing ${repo.full_name}…`, sourceId))
  await deps.api.updateSource(projectId, sourceId, {
    config: { repo: repo.full_name, branch: repo.default_branch }
  })
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
