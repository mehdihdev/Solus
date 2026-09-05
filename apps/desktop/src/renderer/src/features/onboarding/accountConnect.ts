// The ACCOUNT-scoped OAuth engine (SOLUSDEV-241 / I1). Home binds a provider
// account once — no project, no picker, no sync: choose the grant, run the
// browser handshake, exchange the code, done. Projects attach to the result
// later through the ordinary connect wizard, which skips the sign-in when a
// linked account exists (oauthConnect.ts).
//
// Same shape as the project engine: everything injected, never throws, the
// provider is an argument at every layer.
import type { Connection, OAuthStartResponse } from '../../lib/api/resources'
import type { OAuthBridge } from '../auth/githubOAuth'
import type { AccessChoiceStep } from './accessChoiceStep'
import type { ConnectionState, ConnectStage } from './onboardingStore'
import { noBridgeError } from './oauthConnect'

export interface AccountConnectApi {
  startOAuth: (
    projectId: null,
    provider: string,
    input: { redirect_uri?: string; access?: string }
  ) => Promise<OAuthStartResponse>
  exchangeOAuth: (
    provider: string,
    input: { state: string; code: string }
  ) => Promise<{ connection: Connection }>
}

export interface AccountConnectDeps {
  api: AccountConnectApi
  bridge: OAuthBridge | null
  onProgress: (state: ConnectionState) => void
  /** The connect-time grant choice, BEFORE authorization (it decides the scopes). */
  chooseAccess?: AccessChoiceStep
}

export interface AccountConnectOptions {
  redirectUri: string
  displayName?: string
}

export interface AccountConnectResult {
  ok: boolean
  connectionId?: string
  login?: string | null
  result?: string
  error?: string
}

function busy(stage: ConnectStage, label: string): ConnectionState {
  return { phase: 'busy', stage, label }
}

/** The done line names the REAL account: an opaque id when the provider gave
 *  nothing better, never an invented name. */
export function accountConnectedResult(displayName: string, login: string | null): string {
  return login ? `Connected as ${login}` : `${displayName} account connected`
}

/**
 * Bind one provider account to the signed-in user. Reports progress through
 * `onProgress`; never throws — failures resolve to `{ ok: false, error }`.
 */
export async function runAccountConnect(
  deps: AccountConnectDeps,
  provider: string,
  options: AccountConnectOptions
): Promise<AccountConnectResult> {
  const label = options.displayName ?? provider
  if (!deps.bridge) {
    const error = noBridgeError(label)
    deps.onProgress({ phase: 'error', error })
    return { ok: false, error }
  }
  try {
    const access = deps.chooseAccess ? await deps.chooseAccess() : { access: undefined }
    if ('error' in access) {
      deps.onProgress({ phase: 'error', error: access.error })
      return { ok: false, error: access.error }
    }
    deps.onProgress(busy('authorize', `Authorizing with ${label}…`))
    const start = await deps.api.startOAuth(null, provider, {
      redirect_uri: options.redirectUri,
      ...(access.access ? { access: access.access } : {})
    })
    const callback = await deps.bridge.awaitOAuth(start.authorize_url, start.state)
    if (callback.error) {
      deps.onProgress({ phase: 'error', error: callback.error })
      return { ok: false, error: callback.error }
    }
    if (!callback.code) {
      const error = `${label} sign-in was cancelled.`
      deps.onProgress({ phase: 'error', error })
      return { ok: false, error }
    }
    deps.onProgress(busy('link', `Linking your ${label} account…`))
    const { connection } = await deps.api.exchangeOAuth(provider, {
      state: start.state,
      code: callback.code
    })
    const result = accountConnectedResult(label, connection.account_login)
    deps.onProgress({ phase: 'done', result })
    return { ok: true, connectionId: connection.id, login: connection.account_login, result }
  } catch (error) {
    const message = error instanceof Error ? error.message : `${label} connect failed.`
    deps.onProgress({ phase: 'error', error: message })
    return { ok: false, error: message }
  }
}
