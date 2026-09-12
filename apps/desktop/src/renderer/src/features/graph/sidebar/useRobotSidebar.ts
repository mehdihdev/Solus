// What the robot sidebar can prove (SOLUSDEV-250 P4): the category tree from the graph
// snapshot alone, and three per-robot reads — active real bench sessions, pending link
// suggestions, config provenance — cached per robot for the life of one snapshot, so
// selecting never refetches and a revision bump is the only refresh.
import { useEffect, useState } from 'react'
import {
  ROBOT_CATEGORIES,
  ROBOT_CATEGORY_LABELS,
  getHardwareConfig,
  listHardwareSuggestions,
  type HardwareConfig,
  type HardwareSuggestion,
  type RobotCategory
} from '../../../lib/api/hardware'
import {
  listBenchSessions,
  type BenchSession,
  type Entity,
  type Relation
} from '../../../lib/api/resources'

export interface CategoryRow {
  key: RobotCategory
  label: string
  parts: Entity[]
}

export function childrenOf(
  id: string,
  entities: readonly Entity[],
  relations: readonly Relation[]
): Entity[] {
  const ids = new Set(
    relations
      .filter((edge) => edge.type === 'contains' && edge.from_entity_id === id)
      .map((edge) => edge.to_entity_id)
  )
  return entities.filter((entity) => ids.has(entity.id))
}

/** The seven categories in ROBOT_CATEGORIES order; a category the snapshot lacks is empty. */
export function robotCategories(
  robot: Entity,
  entities: readonly Entity[],
  relations: readonly Relation[]
): CategoryRow[] {
  const nodes = childrenOf(robot.id, entities, relations).filter(
    (entity) => entity.type === 'robot_category'
  )
  return ROBOT_CATEGORIES.map((key) => {
    const node = nodes.find((entity) => entity.properties?.category === key)
    return {
      key,
      label: ROBOT_CATEGORY_LABELS[key],
      parts: node ? childrenOf(node.id, entities, relations) : []
    }
  })
}

export type Connection = 'streaming' | 'none' | 'unknown'
export interface RobotReads {
  identityNote?: string
  connection: Connection
  suggestions: HardwareSuggestion[]
  /** Part entity id → the distinct provenance `by` values the config carries, verbatim. */
  provenance: Record<string, string>
}

/** A session streams this robot when its device ref is the prefix of any part's source key. */
function connectionOf(sessions: BenchSession[], parts: readonly Entity[]): Connection {
  const refs = new Set(
    parts.flatMap((part) => (part.source_key ? [part.source_key.split('/')[0]] : []))
  )
  return sessions.some((session) => {
    const ref = session.device?.device_ref
    return typeof ref === 'string' && refs.has(ref)
  })
    ? 'streaming'
    : 'none'
}

function provenanceTags(config: HardwareConfig): Record<string, string> {
  const tags: Record<string, string[]> = {}
  for (const [path, record] of Object.entries(config.provenance ?? {})) {
    const partId = /^parts\.([^.]+)/.exec(path)?.[1]
    if (partId && !tags[partId]?.includes(record.by)) (tags[partId] ??= []).push(record.by)
  }
  return Object.fromEntries(Object.entries(tags).map(([id, by]) => [id, by.join('/')]))
}

async function readRobot(
  projectId: string,
  robotId: string,
  parts: readonly Entity[]
): Promise<RobotReads> {
  const [sessions, suggestions, config] = await Promise.allSettled([
    listBenchSessions(projectId, { status: 'active', mode: 'real' }),
    listHardwareSuggestions(projectId),
    getHardwareConfig(projectId, robotId)
  ])
  return {
    connection: sessions.status === 'fulfilled' ? connectionOf(sessions.value, parts) : 'unknown',
    suggestions:
      suggestions.status === 'fulfilled'
        ? suggestions.value.filter((suggestion) => suggestion.candidate_robot_id === robotId)
        : [],
    provenance: config.status === 'fulfilled' ? provenanceTags(config.value.config) : {},
    identityNote:
      config.status === 'fulfilled' && config.value.config.identity?.binding.startsWith('usb:port-')
        ? 'identity from the USB port — keep it in this port'
        : ''
  }
}

// Keyed by the snapshot's entity array: a new snapshot is a new (empty) cache, and the old
// one dies with the array — nothing outlives a project switch or a sign-out.
const CACHE = new WeakMap<readonly Entity[], Map<string, Promise<RobotReads>>>()

function cachedRead(
  projectId: string,
  robot: Entity,
  entities: readonly Entity[],
  relations: readonly Relation[]
): Promise<RobotReads> {
  const perSnapshot = CACHE.get(entities) ?? new Map<string, Promise<RobotReads>>()
  CACHE.set(entities, perSnapshot)
  const hit = perSnapshot.get(robot.id)
  if (hit) return hit
  const parts = robotCategories(robot, entities, relations).flatMap((row) => row.parts)
  const read = readRobot(projectId, robot.id, parts)
  perSnapshot.set(robot.id, read)
  return read
}

interface Stored {
  entities: readonly Entity[]
  robotId: string
  reads: RobotReads
}

/** The reads for one robot, or null while they are unknown; offline reads nothing. */
export function useRobotReads(
  projectId: string,
  robot: Entity,
  online: boolean,
  entities: readonly Entity[],
  relations: readonly Relation[]
): RobotReads | null {
  const [stored, setStored] = useState<Stored | null>(null)
  useEffect(() => {
    if (!online) return
    let live = true
    void cachedRead(projectId, robot, entities, relations).then((reads) => {
      if (live) setStored({ entities, robotId: robot.id, reads })
    })
    return () => {
      live = false
    }
  }, [projectId, robot, online, entities, relations])
  return online && stored?.entities === entities && stored.robotId === robot.id
    ? stored.reads
    : null
}
