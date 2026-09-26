import { useEffect, useRef } from 'react'
import { Button } from '../../../components/ui/Button'
import type { Entity } from '../../../lib/api/resources'
import type { CandidateApi } from '../../../lib/api/resources.sourcing'
import { groundingLabel, safeHttps, tradeOffLine } from '../../sourcing/sourcingLogic'
import { useSourcing, type SourcingData } from '../../sourcing/useSourcing'

interface Props {
  projectId: string
  query: string
  disabled: boolean
  onCreated: (entity: Entity) => void
}

/** Uses the shared sourcing engine; typing alone never starts a metered job. */
export function InlineSupplierResults({
  projectId,
  query,
  disabled,
  onCreated
}: Props): React.JSX.Element {
  const data = useSourcing(projectId)
  const reported = useRef<string | null>(null)
  useEffect(() => {
    if (data.selected && data.selected.id !== reported.current) {
      reported.current = data.selected.id
      onCreated(data.selected)
    }
  }, [data.selected, onCreated])
  return (
    <div className="hardware-supplier-results">
      <Button
        size="sm"
        kind="bare"
        disabled={disabled || data.busy || !query.trim() || data.phase === 'searching'}
        onClick={() =>
          void data.actions.submit({ door: 'workspace', spec: { text: query.trim() } })
        }
      >
        Search suppliers (uses credits)
      </Button>
      <SupplierState data={data} disabled={disabled} />
      {data.selected && <p role="status">Added {data.selected.name} as a planned part.</p>}
    </div>
  )
}

function CandidateFacts({ candidate }: { candidate: CandidateApi }): React.JSX.Element {
  const source = safeHttps(candidate.source_url)
  const rows = [
    ['Supplier', candidate.supplier ?? candidate.manufacturer],
    ['Part number', candidate.part_number],
    ['Voltage', candidate.voltage_v == null ? null : `${candidate.voltage_v} V`],
    ['Protocol', candidate.protocol],
    ['Availability', candidate.availability]
  ]
  return (
    <div>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value ?? 'Unknown'}</dd>
          </div>
        ))}
      </dl>
      <p>{tradeOffLine(candidate)}</p>
      {candidate.notes && <p>{candidate.notes}</p>}
      {candidate.flags.map((flag) => (
        <p key={flag}>{flag}</p>
      ))}
      {source && (
        <a href={source} target="_blank" rel="noopener noreferrer">
          Source evidence
        </a>
      )}
    </div>
  )
}

function SupplierState({
  data,
  disabled
}: {
  data: SourcingData
  disabled: boolean
}): React.JSX.Element {
  return (
    <>
      {data.phase === 'searching' && <p role="status">Finding supplier candidates…</p>}
      {data.error && <p role="alert">{data.error}</p>}
      {data.phase === 'candidates' && data.request?.candidates.length === 0 && (
        <p>No suitable supplier candidates found.</p>
      )}
      {data.request && data.phase !== 'searching' && (
        <ul aria-label="Supplier results">
          {data.request.candidates.map((candidate) => (
            <li key={candidate.id}>
              <div>
                <span>{candidate.name}</span> <small>{groundingLabel(candidate)}</small>
              </div>
              <Button
                size="sm"
                disabled={disabled || data.busy || data.phase === 'selected'}
                aria-label={`Add ${candidate.name}`}
                onClick={() => void data.actions.select(candidate.id)}
              >
                Add
              </Button>
              <details>
                <summary>Specs and evidence</summary>
                <CandidateFacts candidate={candidate} />
              </details>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
