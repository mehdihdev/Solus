// What the robot sidebar can prove (SOLUSDEV-250 P4): the parts the robot `contains`
// directly (SOLUSDEV-326) from the graph snapshot alone, and four per-robot reads — active
// real bench sessions, pending link suggestions, config provenance, the robot's own brains —
// cached per robot for the life of one snapshot, so selecting never refetches and a revision
// bump is the only refresh.
import { useEffect, useState } from 'react'
import {
  getEntityHardwareConfig,
  getHardwareConfig,
  listHardwareSuggestions,
  type EntityHardwareConfigOut,
  type HardwareConfig,
  type HardwareSuggestion
} from '../../../lib/api/hardware'
import {
  listBenchSessions,
  type BenchSession,
  type Entity,
  type Relation
} from '../../../lib/api/resources'

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

/** A brain known only by its USB port position (binding `port-<location>`, device ref
 *  `usb:port-<location>`) stays this robot's only while it stays in that port. */
function portNote(own: EntityHardwareConfigOut): string {
  const byPort = (own.config?.identity ?? []).some(
    (brain) => brain.binding?.kind === 'usb_serial' && brain.binding.binding.startsWith('port-')
  )
  return byPort ? 'identity from the USB port — keep it in this port' : ''
}

async function readRobot(
  projectId: string,
  robotId: string,
  parts: readonly Entity[]
): Promise<RobotReads> {
  const [sessions, suggestions, config, own] = await Promise.allSettled([
    listBenchSessions(projectId, { status: 'active', mode: 'real' }),
    listHardwareSuggestions(projectId),
    getHardwareConfig(projectId, robotId),
    getEntityHardwareConfig(projectId, robotId)
  ])
  return {
    connection: sessions.status === 'fulfilled' ? connectionOf(sessions.value, parts) : 'unknown',
    suggestions:
      suggestions.status === 'fulfilled'
        ? suggestions.value.filter((suggestion) => suggestion.candidate_robot_id === robotId)
        : [],
    provenance: config.status === 'fulfilled' ? provenanceTags(config.value.config) : {},
    identityNote: own.status === 'fulfilled' ? portNote(own.value) : ''
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
  const read = readRobot(projectId, robot.id, childrenOf(robot.id, entities, relations))
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
