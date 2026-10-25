// Body B of the side panel (design template): the focused node's connections, one card
// per neighbourhood edge — the other node, the relation, the real edge sentence, and a
// status pill derived from open findings on either endpoint. Reads the same fetched
// neighbourhood the focus store already holds; never a second request.
import { useState } from 'react'
import { Mono } from '../../../components/ui/Mono'
import type { Entity, Relation } from '../../../lib/api/resources'
import { selectNeighborhood, useFocusStore } from '../../workspace/focusStore'
import { edgeSentence, relationWords } from '../navigation/edgeSentence'
import type { FindingBadge, FindingsBySubject } from '../useFindings'

export type ConnectionTone = 'ok' | 'warn' | 'err'

/** No open finding → In sync; info/warning → Review; critical → Broken. */
export function connectionStatus(...badges: readonly (FindingBadge | null | undefined)[]): {
  label: string
  tone: ConnectionTone
} {
  const worst = badges.reduce<FindingBadge | null>((acc, badge) => {
    if (!badge) return acc
    if (!acc) return badge
    return RANK[badge.severity] > RANK[acc.severity] ? badge : acc
  }, null)
  if (!worst) return { label: 'In sync', tone: 'ok' }
  return worst.severity === 'critical'
    ? { label: 'Broken', tone: 'err' }
    : { label: 'Review', tone: 'warn' }
}
const RANK = { info: 0, warning: 1, critical: 2 } as const

interface Connection {
  edge: Relation
  other: Entity | undefined
  effect: string
}

function connectionsOf(
  entity: Entity,
  neighborhood: { entities: readonly Entity[]; edges: readonly Relation[] } | null
): Connection[] {
  if (!neighborhood) return []
  const byId = new Map(neighborhood.entities.map((node) => [node.id, node]))
  return neighborhood.edges
    .filter((edge) => edge.from_entity_id === entity.id || edge.to_entity_id === entity.id)
    .map((edge) => {
      const otherId = edge.from_entity_id === entity.id ? edge.to_entity_id : edge.from_entity_id
      return {
        edge,
        other: byId.get(otherId),
        effect: edgeSentence(edge, byId.get(edge.from_entity_id), byId.get(edge.to_entity_id))
      }
    })
}

export function ConnectionsPanel({
  entity,
  findings,
  onReveal
}: {
  entity: Entity
  findings: FindingsBySubject
  onReveal: (entityId: string) => void
}): React.JSX.Element {
  const neighborhood = useFocusStore(selectNeighborhood)
  const [q, setQ] = useState('')
  const needle = q.trim().toLowerCase()
  const all = connectionsOf(entity, neighborhood)
  const shown = needle
    ? all.filter(
        (c) =>
          (c.other?.name ?? '').toLowerCase().includes(needle) ||
          c.effect.toLowerCase().includes(needle)
      )
    : all
  return (
    <section className="node-panel-connections" aria-label="Connections">
      <div className="node-panel-section-row">
        <Mono size={10} ls="0.08em">
          CONNECTIONS · {shown.length}
        </Mono>
        <input
          type="search"
          aria-label="Search connections"
          placeholder="Search"
          value={q}
          onChange={(event) => setQ(event.target.value)}
        />
      </div>
      {shown.map(({ edge, other, effect }) => {
        const status = connectionStatus(findings.get(entity.id), other && findings.get(other.id))
        return (
          <article key={edge.id} className="conn-card" data-domain={other?.domain}>
            <button
              type="button"
              disabled={!other}
              onClick={() => other && onReveal(other.id)}
              aria-label={other ? `Reveal ${other.name}` : undefined}
            >
              <i className="graph-domain-dot" aria-hidden="true" />
              <strong>{other?.name ?? edge.to_entity_id}</strong>
              <Mono size={10}>{relationWords(edge.type)}</Mono>
            </button>
            <div className="conn-card-body">
              <p>{effect}</p>
              <span className="conn-status" data-tone={status.tone}>
                {status.label}
              </span>
            </div>
          </article>
        )
      })}
      {all.length > 0 && shown.length === 0 && (
        <p className="node-panel-empty">No connections match “{q.trim()}”</p>
      )}
      {all.length === 0 && <p className="node-panel-empty">No connections in the graph yet.</p>}
      {neighborhood?.truncated && (
        <p className="node-panel-empty">Showing the nearest connections; the graph has more.</p>
      )}
    </section>
  )
}
