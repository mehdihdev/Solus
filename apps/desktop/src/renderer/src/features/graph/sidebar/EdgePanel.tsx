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

/** One `checker_results` item (docs/api/relations.md §2); `status`/`at` are absent on items
 *  written before statuses existed, which render as before (`rule_id · severity`). */
interface CheckerRow {
  rule_id: string
  status: string | null
  severity: string | null
  message: string | null
  at: string | null
}

/** Only a failure is a problem: `unknown_input` means a fact was missing, not a fault. */
const STATUS_WORDS: Record<string, string> = {
  fail: 'failed',
  pass: 'passed',
  inconclusive: 'inconclusive',
  unknown_input: 'could not check'
}

function toRow(item: unknown): CheckerRow | [] {
  if (typeof item !== 'object' || item === null) return []
  const { rule_id, status, severity, message, at } = item as Record<string, unknown>
  if (typeof rule_id !== 'string') return []
  return {
    rule_id,
    status: text(status),
    severity: text(severity),
    message: text(message),
    at: text(at)
  }
}

function rowLabel(row: CheckerRow): string {
  const word = row.status ? STATUS_WORDS[row.status] : undefined
  const severity = word === undefined || row.status === 'fail' ? row.severity : null
  return [row.rule_id, word, severity].filter(Boolean).join(' · ')
}

function CheckerRows({ rows }: { rows: CheckerRow[] }): React.JSX.Element {
  return (
    <ul>
      {rows.map((row, index) => (
        <li key={index}>
          <span>{rowLabel(row)}</span>
          {row.message && <p>{row.message}</p>}
          {row.at && (
            <time dateTime={row.at}>{`${row.at.slice(0, 16).replace('T', ' ')} UTC`}</time>
          )}
        </li>
      ))}
    </ul>
  )
}

/** Checker rows when the shape fits, passes folded under one summary; otherwise the JSON. */
function CheckerResults({ value }: { value: unknown }): React.JSX.Element {
  const rows = Array.isArray(value) ? value.flatMap(toRow) : []
  if (!Array.isArray(value) || rows.length !== value.length)
    return <pre className="node-sidebar-mono">{JSON.stringify(value, null, 2)}</pre>
  const passed = rows.filter((row) => row.status === 'pass')
  return (
    <>
      <CheckerRows rows={rows.filter((row) => row.status !== 'pass')} />
      {passed.length > 0 && (
        <details>
          <summary>{`${passed.length} passed`}</summary>
          <CheckerRows rows={passed} />
        </details>
      )}
    </>
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
