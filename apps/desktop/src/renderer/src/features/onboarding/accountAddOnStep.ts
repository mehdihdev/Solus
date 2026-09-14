import type { HostedStatus, IntegrationHosted } from '../../lib/api/resources'
import type { OAuthBridge } from '../auth/githubOAuth'
import type { ConnectionState } from './onboardingStore'

export interface AccountAddOnDeps {
  hosted: IntegrationHosted | null
  bridge: OAuthBridge | null
  isCancelled: () => boolean
  onProgress: (state: ConnectionState) => void
  api: {
    getAccountHosted: (id: string, server: string) => Promise<HostedStatus>
    startAccountHosted: (
      id: string,
      server: string
    ) => Promise<{ authorize_url: string; state: string }>
    exchangeAccountHosted: (
      id: string,
      server: string,
      body: { state: string; code: string }
    ) => Promise<HostedStatus>
  }
}
export function accountAddOnStep(deps: AccountAddOnDeps): (id: string) => Promise<string | null> {
  return async (id) => {
    const { hosted, bridge } = deps
    if (!hosted || !bridge || deps.isCancelled()) return null
    const incomplete = `${hosted.display_name} setup incomplete; continue setup in Home.`
    const enabled = `${hosted.display_name} enabled`
    try {
      const current = await deps.api.getAccountHosted(id, hosted.server)
      if (deps.isCancelled()) return null
      if (current.state === 'ready') return enabled
      deps.onProgress({ phase: 'busy', stage: 'link', label: `Connecting ${hosted.display_name}…` })
      return (await authorize(deps, id)) ? enabled : incomplete
    } catch {
      return incomplete
    }
  }
}

async function authorize(deps: AccountAddOnDeps, id: string): Promise<boolean> {
  const { hosted, bridge } = deps
  if (!hosted || !bridge || deps.isCancelled()) return false
  const start = await deps.api.startAccountHosted(id, hosted.server)
  if (deps.isCancelled()) return false
  const callback = await bridge.awaitOAuth(start.authorize_url, start.state)
  if (deps.isCancelled() || callback.error || !callback.code) return false
  const status = await deps.api.exchangeAccountHosted(id, hosted.server, {
    state: start.state,
    code: callback.code
  })
  return !deps.isCancelled() && status.state === 'ready'
}
