// SOLUSDEV-216 / ADR-039: the "Link organization" orchestration.
//   install/start → system browser (install URL) → loopback with the install
//   wait → install/complete.
// Transport and the Electron bridge are injected so this is unit-testable
// without React or Electron. Never throws: every path resolves to an outcome.
import { planLimitFromError, type PlanLimitRefusal } from '../../lib/api/planLimit'
import {
  githubOrgErrorCode,
  type GithubInstallCompleteInput,
  type GithubInstallResult,
  type GithubInstallStart,
  type GithubOrgErrorCode,
  type GithubSetupAction,
  type TeamInstallation
} from '../../lib/api/resources.teamGithub'

/** The slice of the preload OAuth bridge the install flow uses. Main opens the
 *  install URL in the system browser and owns the (longer) install timeout. */
export interface InstallBridge {
  getConnectorRedirectUrl: () => Promise<string>
  awaitOAuth: (
    authorizeUrl: string,
    expectedState: string,
    options: { install: true }
  ) => Promise<{
    code?: string
    error?: string
    installationId?: number
    setupAction?: GithubSetupAction
  }>
}

export interface InstallFlowDeps {
  start: (teamId: string, redirectUri: string) => Promise<GithubInstallStart>
  complete: (teamId: string, input: GithubInstallCompleteInput) => Promise<GithubInstallResult>
  /** Null outside the desktop app. */
  bridge: InstallBridge | null
}

export type InstallOutcome =
  | { kind: 'linked'; installation: TeamInstallation }
  | { kind: 'requested' }
  | { kind: 'cancelled' }
  | { kind: 'refused'; code: GithubOrgErrorCode; limit: PlanLimitRefusal | null }
  | { kind: 'failed'; reason: 'no_bridge' | 'loopback' | 'error'; message: string | null }

function refusalOf(error: unknown): InstallOutcome {
  const code = githubOrgErrorCode(error)
  if (code) return { kind: 'refused', code, limit: planLimitFromError(error) }
  if (planLimitFromError(error)) {
    return { kind: 'refused', code: 'plan_limit_reached', limit: planLimitFromError(error) }
  }
  return { kind: 'failed', reason: 'error', message: null }
}

export async function runGithubInstall(
  deps: InstallFlowDeps,
  teamId: string
): Promise<InstallOutcome> {
  const { bridge } = deps
  if (!bridge) return { kind: 'failed', reason: 'no_bridge', message: null }
  try {
    const redirectUri = await bridge.getConnectorRedirectUrl()
    const start = await deps.start(teamId, redirectUri)
    const callback = await bridge.awaitOAuth(start.install_url, start.state, { install: true })
    if (callback.error) return { kind: 'failed', reason: 'loopback', message: callback.error }
    if (!callback.code) return { kind: 'cancelled' }
    return await deps.complete(teamId, {
      state: start.state,
      code: callback.code,
      setup_action: callback.setupAction ?? 'install',
      ...(callback.installationId === undefined ? {} : { installation_id: callback.installationId })
    })
  } catch (error: unknown) {
    return refusalOf(error)
  }
}

/** The main process only opens https links externally; never render another scheme. */
export function safeHttpsUrl(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    return new URL(url).protocol === 'https:' ? url : null
  } catch {
    return null
  }
}
