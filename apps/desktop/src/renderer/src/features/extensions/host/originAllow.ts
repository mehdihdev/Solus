// SOLUSDEV-235 / SEC-C1 — the single origin-allowlist decision for every
// method that reaches a third-party origin (`net.fetch` and `ui.openExternal`).
// One predicate, two callers: a divergence between the two would be an
// exfiltration channel, so handlers import from here and never re-derive it.
import type { BridgePolicy } from './policySnapshot'

type NetworkPolicy = Pick<BridgePolicy, 'grantedNetwork'> &
  Partial<Pick<BridgePolicy, 'storeLinks'>>

function parseUrl(url: string): URL | null {
  try {
    return new URL(url)
  } catch {
    return null
  }
}

/** https AND `origin` ∈ the granted `permissions.network` (exact origin match). */
export function isGrantedOrigin(policy: NetworkPolicy, url: string): boolean {
  const parsed = parseUrl(url)
  return (
    parsed !== null && parsed.protocol === 'https:' && policy.grantedNetwork.includes(parsed.origin)
  )
}

/** The URL equals one of the manifest's `store.links` values verbatim. */
export function isStoreLink(policy: NetworkPolicy, url: string): boolean {
  return (policy.storeLinks ?? []).includes(url)
}
