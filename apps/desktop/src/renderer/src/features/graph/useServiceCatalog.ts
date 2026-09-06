import { useEffect, useSyncExternalStore } from 'react'
import { apiBaseUrl, createApiClient } from '../../lib/api/client'
import { useAuthStore } from '../../store/authStore'
import { ServiceCatalog, type CatalogSnapshot } from './serviceCatalog'

const identityOf = (): string => {
  const auth = useAuthStore.getState()
  return `${auth.status}:${auth.user?.email ?? ''}`
}
let retained: { identity: string; catalog: ServiceCatalog } | null = null
export function clearServiceCatalog(): void {
  retained?.catalog.dispose()
  retained = null
}
useAuthStore.subscribe((next, previous) => {
  if (next.status !== previous.status || next.user?.email !== previous.user?.email)
    clearServiceCatalog()
})
function catalogFor(identity: string): ServiceCatalog {
  if (retained?.identity === identity) return retained.catalog
  clearServiceCatalog()
  const client = createApiClient({
    baseUrl: apiBaseUrl,
    getToken: () => {
      if (identityOf() !== identity) throw new Error('The account session has ended.')
      return useAuthStore.getState().accessToken
    }
  })
  const catalog = new ServiceCatalog(client)
  retained = { identity, catalog }
  return catalog
}
export function useServiceCatalog(enabled: boolean): {
  catalog: ServiceCatalog
  state: CatalogSnapshot
} {
  const identity = useAuthStore((state) => `${state.status}:${state.user?.email ?? ''}`)
  const catalog = catalogFor(identity)
  const state = useSyncExternalStore(catalog.subscribe, catalog.snapshot)
  useEffect(() => {
    if (enabled) void catalog.loadAccounts()
  }, [enabled, catalog])
  return { catalog, state }
}
