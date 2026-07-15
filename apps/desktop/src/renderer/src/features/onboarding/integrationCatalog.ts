// Live integration catalog (SOLUSDEV-100, design review Q1=B). The tile list is
// driven by GET /integrations (the backend connector registry) so new
// connectors appear without frontend edits — the drift that left Altium
// invisible after SOLUSDEV-102. Curated display metadata + still-simulated
// roster members come from integrations.constants; the API is unreachable in
// dev bypass / offline, where we degrade to the curated static list.
import { listIntegrations, type Integration as ApiIntegration } from '../../lib/api/resources'
import { INTEGRATIONS, type Integration } from './integrations.constants'

/** How a tile connects: the real GitHub OAuth bridge, a real committed-export
 * file pick, or the prototype's simulated animation. */
export type ConnectMode = 'github-oauth' | 'export-file' | 'simulated'

export interface CatalogEntry extends Integration {
  readonly mode: ConnectMode
}

/** Display metadata for live providers outside the curated onboarding four. */
const EXTRA_DISPLAY: readonly Integration[] = [
  {
    id: 'altium',
    name: 'Altium',
    kind: 'PCB / Schematic',
    mark: 'Al',
    steps: ['Reading committed export…', 'Parsing Protel netlist…', 'Building electrical graph…'],
    result: 'Connected — components, nets, connectivity'
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
    mark: type.slice(0, 2).toUpperCase(),
    steps: ['Connecting…', 'Syncing…'],
    result: 'Connected'
  }
}

function modeFor(type: string, live: ApiIntegration | undefined): ConnectMode {
  if (!live) return 'simulated'
  if (type === 'github') return 'github-oauth'
  // Committed-export connectors (KiCad, Altium, …): no tool credential, the
  // export content is the config — drivable with a file pick.
  if (live.auth_kind === 'none' && live.config_fields.includes('export')) return 'export-file'
  // Live but not drivable in-app yet (e.g. GitLab OAuth has no bridge flow).
  return 'simulated'
}

/** Offline/dev-bypass catalog: the curated four, optimistically connectable —
 * the click-time guards (linked project, bridge) decide real vs simulated. */
export const FALLBACK_CATALOG: readonly CatalogEntry[] = INTEGRATIONS.map((display) => ({
  ...display,
  mode:
    display.id === 'github'
      ? ('github-oauth' as const)
      : display.id === 'kicad'
        ? ('export-file' as const)
        : ('simulated' as const)
}))

/**
 * Build the tile list from the live connector registry: curated tiles first
 * (real when the backend has them, simulated placeholders otherwise), then any
 * additional drivable live providers. Falls back to the static curated list
 * when the API is unreachable.
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

  const curated = INTEGRATIONS.map((display) => ({
    ...display,
    mode: modeFor(display.id, byType.get(display.id))
  }))
  const extras = live
    .filter((integration) => !INTEGRATIONS.some((c) => c.id === integration.type))
    .map((integration) => ({
      ...displayFor(integration.type),
      mode: modeFor(integration.type, integration)
    }))
    // A non-curated provider we cannot drive would render a dishonest
    // fake-connect tile — hide it until its real flow lands.
    .filter((entry) => entry.mode !== 'simulated')

  return [...curated, ...extras]
}
