// Live integration catalog (SOLUSDEV-100, de-simulated in SOLUSDEV-152). The
// tile list is driven by GET /integrations (the backend connector registry) so
// new connectors appear without frontend edits. Only providers the app can
// REALLY drive are listed — a tile that cannot connect is hidden, never faked.
// When the API is unreachable (dev bypass / offline) we degrade to the curated
// drivable pair; click-time guards report honest errors if connect can't run.
import {
  listIntegrations,
  type Integration as ApiIntegration,
  type IntegrationAccessModes,
  type IntegrationSelection
} from '../../lib/api/resources'
import { INTEGRATIONS, type Integration } from './integrations.constants'

/** How a tile really connects: the desktop OAuth bridge (any provider) or a
 * committed-export file pick. There is no simulated mode — undrivable
 * providers are hidden. */
export type ConnectMode = 'oauth' | 'export-file'

export interface CatalogEntry extends Integration {
  readonly mode: ConnectMode
  /** The connector's required config keys, straight from the live registry.
   * Drives the generated details form when there is nothing to pick. */
  readonly configFields: readonly string[]
  /** How the connector lets a user choose what to track (repos, documents, …),
   * or null when there is nothing to pick. Drives the generic picker, so a new
   * connector becomes pickable with no change here. */
  readonly selection: IntegrationSelection | null
  /** The grants the connector offers at connect time, or null when there is no
   * choice. Drives the generic access picker (SOLUS-ONS-A2). */
  readonly accessModes: IntegrationAccessModes | null
}

/** Display metadata for live providers outside the curated onboarding pair.
 * Copy only — nothing here decides whether or how a provider connects, so a
 * new connector still appears (with a generic tile) without being listed. */
const EXTRA_DISPLAY: readonly Integration[] = [
  {
    id: 'altium',
    name: 'Altium',
    kind: 'PCB / Schematic — committed netlist export',
    mark: 'Al'
  },
  { id: 'gitlab', name: 'GitLab', kind: 'Code', mark: 'GL' },
  { id: 'onshape', name: 'Onshape', kind: 'Mechanical CAD — cloud', mark: 'On' }
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
 * drive it — null hides the tile. Both branches key off the connector's own
 * declared shape, never a provider id, so a new connector the backend registers
 * becomes connectable here with no code change. */
function modeFor(live: ApiIntegration | undefined): ConnectMode | null {
  if (!live) return null
  // Any OAuth connector: the desktop loopback bridge drives the authorize +
  // exchange, then the provider's config_fields drive the configure step.
  if (live.auth_kind === 'oauth') return 'oauth'
  // Committed-export connectors (KiCad, Altium, …): no tool credential, the
  // export content is the config — drivable with a file pick.
  if (live.auth_kind === 'none' && live.config_fields.includes('export')) return 'export-file'
  return null
}

/** Curated shapes used only for the offline fallback, where no live registry
 * answer is available. */
type CuratedEntry = {
  mode: ConnectMode
  configFields: readonly string[]
  selection: IntegrationSelection | null
  accessModes: IntegrationAccessModes | null
}

const CURATED: Readonly<Record<string, CuratedEntry>> = {
  github: {
    mode: 'oauth',
    configFields: ['repo', 'branch'],
    selection: { mode: 'single', config_key: 'repo', label: 'repository' },
    accessModes: null
  },
  kicad: { mode: 'export-file', configFields: ['export'], selection: null, accessModes: null }
}

/** Offline/dev-bypass catalog: the curated drivable pair, optimistically
 * connectable — click-time guards (linked project, bridge) report honest
 * errors when a real connect can't run. */
export const FALLBACK_CATALOG: readonly CatalogEntry[] = INTEGRATIONS.map((display) => ({
  ...display,
  ...CURATED[display.id]
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

  const entry = (integration: ApiIntegration | undefined, display: Integration): CatalogEntry[] => {
    const mode = modeFor(integration)
    if (!mode || !integration) return []
    return [
      {
        ...display,
        mode,
        configFields: integration.config_fields,
        selection: integration.selection ?? null,
        accessModes: integration.access_modes ?? null
      }
    ]
  }

  const curated = INTEGRATIONS.flatMap((display) => entry(byType.get(display.id), display))
  const extras = live
    .filter((integration) => !INTEGRATIONS.some((c) => c.id === integration.type))
    .flatMap((integration) => entry(integration, displayFor(integration.type)))

  return [...curated, ...extras]
}
