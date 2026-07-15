// React binding for the live integration catalog (SOLUSDEV-100): renders the
// curated fallback immediately, upgrades to the backend registry when it loads.
import { useEffect, useState } from 'react'
import { FALLBACK_CATALOG, loadIntegrationCatalog, type CatalogEntry } from './integrationCatalog'

export function useIntegrationCatalog(): readonly CatalogEntry[] {
  const [catalog, setCatalog] = useState<readonly CatalogEntry[]>(FALLBACK_CATALOG)

  useEffect(() => {
    let active = true
    void loadIntegrationCatalog().then((entries) => {
      if (active) setCatalog(entries)
    })
    return () => {
      active = false
    }
  }, [])

  return catalog
}
