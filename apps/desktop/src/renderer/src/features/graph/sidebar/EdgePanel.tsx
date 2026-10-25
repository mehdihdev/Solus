// SOLUSDEV-320 P4-T2 — the sidebar for one selected edge (docs/architecture/
// workspace-navigation.md "Edges with meaning"). Everything shown comes from the
// relation itself, rendered as text; Confirm/Decline exist only for candidates and
// go through `lib/api/edges.ts`. Untrusted strings are never injected as HTML.
import { isCandidate } from '@solus/shared-types'
import { useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { confirmEdge, declineEdge } from '../../../lib/api/edges'
import type { Entity, Relation } from '../../../lib/api/resources'
import { edgeEvidence, edgeSentence, relationWords } from '../navigation/edgeSentence'

export interface EdgePanelProps {
  projectId: string
  relation: Relation
  from: Entity | undefined
  to: Entity | undefined
  onDecided: () => void
  onClose: () => void
}

const FAILED = 'The request failed. Please try again.'

function text(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null
}

/** `{rule_id, severity, message}`-ish rows when the shape fits; otherwise the JSON. */
function CheckerResults({ value }: { value: unknown }): React.JSX.Element {
  const rows = Array.isArray(value)
    ? value.flatMap((item) => {
        if (typeof item !== 'object' || item === null) return []
        const { rule_id, severity, message } = item as Record<string, unknown>
        return typeof rule_id === 'string' ? [{ rule_id, severity, message }] : []
      })
    : []
  if (!Array.isArray(value) || rows.length !== value.length)
    return <pre className="node-sidebar-mono">{JSON.stringify(value, null, 2)}</pre>
  return (
    <ul>
      {rows.map((row, index) => (
        <li key={index}>
          <span>{[row.rule_id, text(row.severity)].filter(Boolean).join(' · ')}</span>
          {text(row.message) && <p>{text(row.message)}</p>}
        </li>
      ))}
    </ul>
  )
}

function Facts({ relation, from, to }: Pick<EdgePanelProps, 'relation' | 'from' | 'to'>) {
  const properties = relation.properties ?? {}
  // `serialize_relation` sends `created_at`; the client `Relation` does not type it yet.
  const createdAt = 'created_at' in relation ? text(relation.created_at) : null
  const facts: [string, string | null][] = [
    ['Type', relationWords(relation.type)],
    [
      'Direction',
      `${from?.name ?? relation.from_entity_id} → ${to?.name ?? relation.to_entity_id}`
    ],
    ['Confidence', `${Math.round((relation.confidence ?? 1) * 100)}%`],
    ['Origin', relation.origin ? relationWords(relation.origin) : null],
    ['Created by', text(properties.created_by)],
    ['Created', createdAt && createdAt.slice(0, 10)],
    ['Matrix cell', text(properties.matrix_cell)]
  ]
  return (
    <ul>
      {facts.map(([label, value]) =>
        value ? (
          <li key={label}>
            <span className="node-sidebar-mono">{label}</span>
            <span>{value}</span>
          </li>
        ) : null
      )}
    </ul>
  )
}

function Decision({
  projectId,
  relation,
  onDecided
}: Pick<EdgePanelProps, 'projectId' | 'relation' | 'onDecided'>): React.JSX.Element {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const decide = (action: () => Promise<unknown>): void => {
    setBusy(true)
    setError(null)
    action().then(onDecided, (failure: unknown) => {
      setError(failure instanceof Error ? failure.message : FAILED)
      setBusy(false)
    })
  }
  return (
    <>
      <div className="node-sidebar-actions">
        <Button
          kind="primary"
          size="sm"
          disabled={busy}
          onClick={() => decide(() => confirmEdge(projectId, relation.id))}
        >
          Confirm
        </Button>
        <Button
          kind="danger"
          size="sm"
          disabled={busy}
          onClick={() => decide(() => declineEdge(projectId, relation.id))}
        >
          Decline
        </Button>
      </div>
      {error && <p role="alert">{error}</p>}
    </>
  )
}

export function EdgePanel(props: EdgePanelProps): React.JSX.Element {
  const { relation, from, to } = props
  const evidence = edgeEvidence(relation.properties)
  const checkerResults = relation.properties?.checker_results
  return (
    <section aria-label="Selected edge">
      <h2>{edgeSentence(relation, from, to)}</h2>
      <Facts relation={relation} from={from} to={to} />
      <h3>Evidence</h3>
      {evidence.length === 0 ? (
        <p>No evidence recorded.</p>
      ) : (
        <ul>
          {evidence.map((item, index) => (
            <li key={index}>
              {`${relationWords(item.kind)}: ${item.ref}${item.detail ? ` — ${item.detail}` : ''}`}
            </li>
          ))}
        </ul>
      )}
      {checkerResults !== undefined && (
        <>
          <h3>Checker results</h3>
          <CheckerResults value={checkerResults} />
        </>
      )}
      {isCandidate(relation.origin, relation.confidence) && <Decision {...props} />}
      <div className="node-sidebar-actions">
        <Button kind="bare" size="sm" onClick={props.onClose}>
          Close
        </Button>
      </div>
    </section>
  )
}
