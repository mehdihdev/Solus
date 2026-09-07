// SOLUSDEV-66 (RBT-03) — proposed robot mapping + one-click confirmation.
//
// The user CONFIRMS, never authors: rows arrive as proposals with per-row
// confidence and expandable evidence; accepting is one click, rejecting and
// editing cost exactly the same. Unknown rows say "unknown", carry NO accept
// button, and stay unlinked until the user names them (tier 3's primary flow).
// NOTHING is auto-accepted at any confidence — a wrong motor→joint mapping
// poisons everything downstream, the same catastrophe class as a false
// fingerprint merge.
import { useState, type ReactNode } from 'react'
import type { Decision, MappingProposal, RowStatus } from './proposals.types'

const KIND_LABEL: Record<string, string> = {
  bus_enumeration: 'bus-enumerated',
  firmware_symbol: 'firmware',
  telemetry_channel: 'stream shape'
}

interface RecognitionPanelProps {
  readonly proposals: readonly MappingProposal[]
  readonly onDecision: (id: string, decision: Decision) => void
  /** An extra per-row cell (e.g. a category pick); its control carries its own label. */
  readonly renderRowExtra?: (proposal: MappingProposal) => ReactNode
}

export function RecognitionPanel({
  proposals,
  onDecision,
  renderRowExtra
}: RecognitionPanelProps): React.JSX.Element {
  const [statuses, setStatuses] = useState<Record<string, RowStatus>>(() =>
    Object.fromEntries(proposals.map((p) => [p.id, p.proposedFunction ? 'proposed' : 'unknown']))
  )

  function decide(id: string, decision: Decision, status: RowStatus): void {
    setStatuses((prev) => ({ ...prev, [id]: status }))
    onDecision(id, decision)
  }

  function acceptAll(): void {
    for (const proposal of proposals) {
      if (proposal.proposedFunction !== null && statuses[proposal.id] === 'proposed') {
        decide(proposal.id, { kind: 'accept' }, 'accepted')
      }
    }
  }

  return (
    <div data-testid="recognition-panel">
      <button type="button" onClick={acceptAll}>
        Accept all
      </button>
      <table>
        <thead>
          <tr>
            <th scope="col">Hardware</th>
            <th scope="col">Proposed function</th>
            {renderRowExtra && <th scope="col" />}
            <th scope="col">Confidence</th>
            <th scope="col">Decision</th>
          </tr>
        </thead>
        <tbody>
          {proposals.map((proposal) => (
            <ProposalRow
              key={proposal.id}
              proposal={proposal}
              status={statuses[proposal.id]}
              onDecide={decide}
              extra={renderRowExtra?.(proposal)}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface ProposalRowProps {
  readonly proposal: MappingProposal
  readonly status: RowStatus
  readonly onDecide: (id: string, decision: Decision, status: RowStatus) => void
  readonly extra?: ReactNode
}

function confidenceText(proposal: MappingProposal): string {
  if (proposal.confidence === null) return '—'
  const kind = proposal.evidence[0]?.kind
  return `${Math.round(proposal.confidence * 100)}% · ${KIND_LABEL[kind] ?? ''}`
}

function ProposalRow({ proposal, status, onDecide, extra }: ProposalRowProps): React.JSX.Element {
  const [name, setName] = useState('')
  const [showEvidence, setShowEvidence] = useState(false)

  function save(): void {
    const trimmed = name.trim()
    if (!trimmed) return // an unknown cannot be silently blanked in
    onDecide(proposal.id, { kind: 'edit', functionName: trimmed }, 'edited')
  }

  return (
    <tr data-testid={`proposal-${proposal.id}`}>
      <td className="font-mono">
        {proposal.subject}
        <button type="button" onClick={() => setShowEvidence((v) => !v)}>
          evidence
        </button>
        {showEvidence && <EvidenceList proposal={proposal} />}
      </td>
      <td>{proposal.proposedFunction ?? 'unnamed'}</td>
      {extra !== undefined && <td>{extra}</td>}
      <td>{confidenceText(proposal)}</td>
      <td>
        <span data-testid="row-status">{status}</span>
        {proposal.proposedFunction !== null && status === 'proposed' && (
          <button
            type="button"
            onClick={() => onDecide(proposal.id, { kind: 'accept' }, 'accepted')}
          >
            Accept
          </button>
        )}
        {(status === 'proposed' || status === 'unknown') && (
          <>
            <button
              type="button"
              onClick={() => onDecide(proposal.id, { kind: 'reject' }, 'rejected')}
            >
              Reject
            </button>
            <input
              type="text"
              aria-label={`name for ${proposal.subject}`}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <button type="button" onClick={save}>
              Save
            </button>
          </>
        )}
      </td>
    </tr>
  )
}

function EvidenceList({ proposal }: { proposal: MappingProposal }): React.JSX.Element {
  return (
    <ul>
      {proposal.evidence.map((item) => (
        <li key={`${item.kind}-${item.value}`} style={{ color: 'var(--mut)' }}>
          <span className="font-mono">{item.value}</span> — {item.note}{' '}
          <span className="font-mono">({item.provenance})</span>
        </li>
      ))}
    </ul>
  )
}
