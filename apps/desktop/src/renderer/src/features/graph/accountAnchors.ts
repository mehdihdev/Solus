// Synthetic account anchors (SOLUSDEV-250 P5): a presentation layer concatenated
// upstream of an unmodified buildNavigationIndex. One `integration_account` node per
// account grant (connection, else the source itself) contains that account's document
// roots. `'integration'` is a client-only domain sentinel outside DOMAINS (ADR-027):
// toSharedFocus drops it, so an anchor never enters a focus path, and anchor ids never
// reach PUT /workspace-layout (liveEntityIds stays derived from the real snapshot).
import type { Entity, Relation, Source } from '../../lib/api/resources'
import { buildNavigationIndex } from './navigation/graphIndex'

const PREFIX = 'account:'

export function isAccountAnchor(id: string): boolean {
  return id.startsWith(PREFIX)
}

export interface AnchoredGraph {
  entities: Entity[]
  relations: Relation[]
}

interface Group {
  source: Source
  roots: Entity[]
}

function anchorOf(key: string, { source, roots }: Group): AnchoredGraph {
  const id = `${PREFIX}${key}`
  return {
    entities: [
      {
        id,
        type: 'integration_account',
        domain: 'integration',
        name: source.account_login ?? source.type,
        source_key: null,
        project_id: source.project_id,
        properties: {
          provider: source.type,
          account_login: source.account_login,
          source_ids: [...new Set(roots.map((root) => baseSourceId(root) ?? source.id))]
        }
      }
    ],
    relations: roots.map((root) => ({
      id: `${id}:${root.id}`,
      type: 'contains',
      from_entity_id: id,
      to_entity_id: root.id
    }))
  }
}

function baseSourceId(entity: Entity): string | undefined {
  const base = entity.properties?.base_source_id
  return typeof base === 'string' ? base : (entity.source_id ?? undefined)
}

/** Real roots grouped under their account; roots without a resolvable source stay roots. */
export function withAccountAnchors(
  entities: readonly Entity[],
  relations: readonly Relation[],
  sources: readonly Source[]
): AnchoredGraph {
  const bySource = new Map(sources.map((source) => [source.id, source]))
  const groups = new Map<string, Group>()
  for (const root of buildNavigationIndex(entities, relations).roots) {
    const sourceId = baseSourceId(root)
    const source = sourceId ? bySource.get(sourceId) : undefined
    if (!source || source.type === 'local') continue
    const key = source.connection_id ?? source.id
    const group = groups.get(key) ?? { source, roots: [] }
    groups.set(key, { ...group, roots: [...group.roots, root] })
  }
  const anchors = [...groups].map(([key, group]) => anchorOf(key, group))
  return {
    entities: [...entities, ...anchors.flatMap((anchor) => anchor.entities)],
    relations: [...relations, ...anchors.flatMap((anchor) => anchor.relations)]
  }
}

/** The anchor's documents: its `contains` children in the merged snapshot. */
export function accountDocuments(
  anchorId: string,
  entities: readonly Entity[],
  relations: readonly Relation[]
): Entity[] {
  const ids = new Set(
    relations
      .filter((edge) => edge.type === 'contains' && edge.from_entity_id === anchorId)
      .map((edge) => edge.to_entity_id)
  )
  return entities.filter((entity) => ids.has(entity.id))
}

/** What ProviderMark needs for the anchor's provider. */
export function providerMark(entity: Entity): { id: string; mark: string } {
  const id = String(entity.properties?.provider ?? '')
  // ponytail: same letter-mark fallback the integration catalog uses for an unlisted provider
  return { id, mark: id.slice(0, 2).toUpperCase() }
}
