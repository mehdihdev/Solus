// Live integration catalog (SOLUSDEV-100, de-simulated in SOLUSDEV-152). The
// tile list is driven by GET /integrations (the backend connector registry) so
// new connectors appear without frontend edits. Only providers the app can
// REALLY drive are listed — a tile that cannot connect is hidden, never faked.
// When the API is unreachable (dev bypass / offline) we degrade to the curated
// drivable pair; click-time guards report honest errors if connect can't run.
import { listIntegrations, type Integration as ApiIntegration } from '../../lib/api/resources'
import { INTEGRATIONS, type Integration } from './integrations.constants'

/** How a tile really connects: the GitHub OAuth bridge or a committed-export
 * file pick. There is no simulated mode — undrivable providers are hidden. */
export type ConnectMode = 'github-oauth' | 'export-file'

export interface CatalogEntry extends Integration {
  readonly mode: ConnectMode
}

/** Display metadata for live providers outside the curated onboarding pair. */
const EXTRA_DISPLAY: readonly Integration[] = [
  {
    id: 'altium',
    name: 'Altium',
    kind: 'PCB / Schematic — committed netlist export',
    mark: 'Al'
  }
]

function displayFor(type: string): Integration {
  const known = [...INTEGRATIONS, ...EXTRA_DISPLAY].find((i) => i.id === type)
  if (known) return known
  // A provider the backend grew that we have no copy for yet: generic tile.
  return {
    id: type,
    name: type.charAt(0).toUpperCase() + type.slice(1),
    kind: 'Connector',
    mark: type.slice(0, 2).toUpperCase()
  }
}

/** The real connect mode for a live provider, or null when the app cannot
 * drive it yet (e.g. GitLab OAuth has no bridge flow) — null hides the tile. */
function modeFor(type: string, live: ApiIntegration | undefined): ConnectMode | null {
  if (!live) return null
  if (type === 'github') return 'github-oauth'
  // Committed-export connectors (KiCad, Altium, …): no tool credential, the
  // export content is the config — drivable with a file pick.
  if (live.auth_kind === 'none' && live.config_fields.includes('export')) return 'export-file'
  return null
}

const CURATED_MODES: Readonly<Record<string, ConnectMode>> = {
  github: 'github-oauth',
  kicad: 'export-file'
}

/** Offline/dev-bypass catalog: the curated drivable pair, optimistically
 * connectable — click-time guards (linked project, bridge) report honest
 * errors when a real connect can't run. */
export const FALLBACK_CATALOG: readonly CatalogEntry[] = INTEGRATIONS.map((display) => ({
  ...display,
  mode: CURATED_MODES[display.id]
}))

/**
 * Build the tile list from the live connector registry: curated tiles first
 * (only when the backend registers them), then any additional drivable live
 * providers. Falls back to the curated drivable pair when the API is
 * unreachable. Undrivable providers are never listed.
 */
export async function loadIntegrationCatalog(
  fetchIntegrations: () => Promise<ApiIntegration[]> = listIntegrations
): Promise<readonly CatalogEntry[]> {
  let live: ApiIntegration[]
  try {
    live = await fetchIntegrations()
  } catch {
    return FALLBACK_CATALOG
  }
  const byType = new Map(live.map((integration) => [integration.type, integration]))

  const curated = INTEGRATIONS.flatMap((display) => {
    const mode = modeFor(display.id, byType.get(display.id))
    return mode ? [{ ...display, mode }] : []
  })
  const extras = live
    .filter((integration) => !INTEGRATIONS.some((c) => c.id === integration.type))
    .flatMap((integration) => {
      const mode = modeFor(integration.type, integration)
      return mode ? [{ ...displayFor(integration.type), mode }] : []
    })

  return [...curated, ...extras]
}
