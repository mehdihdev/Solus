import { useEffect, useRef, useState } from 'react'
import {
  proposeExtraction,
  confirmExtraction,
  type ExtractionConfirmation,
  type ExtractionProposal,
  type ExtractionRequest
} from '../../../lib/api/topologyExtraction'
import { readHardwareTopology } from '../../../lib/api/hardwareTopology'
import { useSettingsStore } from '../../../store/settingsStore'
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from '../workspaceSession'
import { HardwareSourcesPanel } from '../hardware/HardwareSourcesPanel'
import { FirmwareTelemetryOffer } from './FirmwareTelemetryOffer'

interface Props {
  projectId: string
  brainId: string
  robots: { id: string; name: string }[]
  onConfirmed?: () => void
}

export function ExtractionReviewCard(props: Props): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  return (
    <Review
      key={`${props.projectId}:${props.brainId}:${generation}:${props.robots.map((r) => r.id).join(',')}`}
      {...props}
      generation={generation}
    />
  )
}

function Review({
  projectId,
  brainId,
  robots,
  onConfirmed,
  generation
}: Props & { generation: number }): React.JSX.Element {
  const mode = useSettingsStore((s) => s.solMode)
  const [robotId, setRobotId] = useState(robots.length === 1 ? robots[0].id : '')
  const [sourceRef, setSourceRef] = useState('')
  const [kind, setKind] = useState<ExtractionRequest['source_kind'] | ''>('')
  const [proposal, setProposal] = useState<ExtractionProposal | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [choices, setChoices] = useState<{ id: string; name: string }[]>([])
  const [selected, setSelected] = useState<Record<number, { name: string; entity_id?: string }>>({})
  const [saved, setSaved] = useState<string | null>(null)
  const pending = useRef<ExtractionConfirmation | null>(null)
  const confirming = useRef(false)
  const epoch = useRef(0)
  useEffect(
    () => () => {
      epoch.current += 1
    },
    []
  )
  const invalidate = (): void => {
    if (pending.current) return
    epoch.current += 1
    setProposal(null)
    setChoices([])
    setSelected({})
    setSaved(null)
    pending.current = null
    setError(null)
    setBusy(false)
  }
  const isCurrent = (ticket: number): boolean =>
    ticket === epoch.current && generation === workspaceSessionGeneration()
  const reviewUnavailable = (): boolean =>
    busy || Boolean(pending.current) || !kind || !sourceRef || !robotId
  const review = async (): Promise<void> => {
    if (!kind || !sourceRef || !robotId || busy || pending.current) return
    const ticket = ++epoch.current
    setBusy(true)
    setError(null)
    setProposal(null)
    setSelected({})
    setSaved(null)
    pending.current = null
    try {
      const result = await proposeExtraction(projectId, robotId, {
        brain_id: brainId,
        source_ref: sourceRef,
        source_kind: kind
      })
      const topology = await readHardwareTopology(projectId, robotId)
      if (isCurrent(ticket)) {
        setChoices(topology.nodes.map(({ id, name }) => ({ id, name })))
        setProposal(result)
      }
    } catch {
      if (isCurrent(ticket))
        setError(
          'The file could not be reviewed. Verify or relink it, check its type, and try again.'
        )
    } finally {
      if (ticket === epoch.current) setBusy(false)
    }
  }
  const confirmationUnavailable = (): boolean =>
    confirming.current || busy || Boolean(saved) || generation !== workspaceSessionGeneration()
  function acceptEvidence(result: Awaited<ReturnType<typeof confirmExtraction>>): void {
    setSaved(
      `Evidence saved: ${result.created} created, ${result.entity_ids.length - result.created} retained. Wiring and runtime configuration are unchanged.`
    )
    onConfirmed?.()
  }
  const confirm = async (): Promise<void> => {
    if (!proposal || !kind || confirmationUnavailable()) return
    const selections = reviewedSelections(selected)
    if (!selections) return
    const input = pending.current ?? {
      brain_id: brainId,
      source_ref: sourceRef,
      source_kind: kind,
      proposal_digest: proposal.proposal_digest,
      operation_id: crypto.randomUUID(),
      selections
    }
    pending.current = input
    confirming.current = true
    const ticket = epoch.current
    setBusy(true)
    setError(null)
    try {
      const result = await confirmExtraction(projectId, robotId, input)
      if (isCurrent(ticket)) {
        acceptEvidence(result)
      }
    } catch {
      if (isCurrent(ticket))
        setError(
          'Confirmation could not be verified. Retry the same selection to recover its result; do not submit it as a new review.'
        )
    } finally {
      confirming.current = false
      if (isCurrent(ticket)) setBusy(false)
    }
  }
  function renderSourceChoices(): React.ReactNode {
    return (
      !pending.current && (
        <>
          {robots.length !== 1 && (
            <label>
              Robot
              <select
                aria-label="Evidence robot"
                value={robotId}
                onChange={(e) => {
                  if (pending.current) return
                  invalidate()
                  setRobotId(e.target.value)
                }}
              >
                <option value="">Choose robot</option>
                {robots.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <HardwareSourcesPanel
            projectId={projectId}
            mode={mode}
            title="Local evidence files"
            onSourceChange={() => {
              if (pending.current) return
              invalidate()
              setSourceRef('')
            }}
            onSelect={(ref) => {
              if (pending.current) return
              invalidate()
              setSourceRef(ref)
            }}
          />
          {sourceRef && <p role="status">Local file selected.</p>}
          <label>
            Evidence type
            <select
              aria-label="Evidence type"
              value={kind}
              onChange={(e) => {
                if (pending.current) return
                invalidate()
                setKind(e.target.value as typeof kind)
              }}
            >
              <option value="">Choose type</option>
              <option value="firmware">Python firmware</option>
              <option value="host_config">Configuration (JSON, YAML or TOML)</option>
            </select>
          </label>
        </>
      )
    )
  }
  function renderProposal(): React.ReactNode {
    return (
      proposal && (
        <>
          <EvidenceResult proposal={proposal} />
          <fieldset disabled={busy || Boolean(pending.current) || Boolean(saved)}>
            <legend>Choose evidence to save</legend>
            {proposal.extraction.rows.map((_row, index) => (
              <div key={index}>
                <label>
                  <input
                    type="checkbox"
                    aria-label={`Select evidence ${index + 1}`}
                    checked={Boolean(selected[index])}
                    onChange={(event) =>
                      setSelected((previous) => {
                        const next = { ...previous }
                        if (event.target.checked) next[index] = { name: '' }
                        else delete next[index]
                        return next
                      })
                    }
                  />
                  Evidence {index + 1}
                </label>
                {selected[index] && (
                  <>
                    <label>
                      Reviewed name
                      <input
                        aria-label={`Reviewed name ${index + 1}`}
                        maxLength={120}
                        value={selected[index].name}
                        onChange={(event) =>
                          setSelected((previous) => ({
                            ...previous,
                            [index]: { ...previous[index], name: event.target.value }
                          }))
                        }
                      />
                    </label>
                    <label>
                      Identity
                      <select
                        aria-label={`Retain identity ${index + 1}`}
                        value={selected[index].entity_id ?? ''}
                        onChange={(event) =>
                          setSelected((previous) => ({
                            ...previous,
                            [index]: {
                              ...previous[index],
                              entity_id: event.target.value || undefined
                            }
                          }))
                        }
                      >
                        <option value="">Create evidence node</option>
                        {choices.map((choice) => (
                          <option key={choice.id} value={choice.id}>
                            {choice.name} · {choice.id}
                          </option>
                        ))}
                      </select>
                    </label>
                  </>
                )}
              </div>
            ))}
          </fieldset>
          <button
            disabled={
              busy ||
              Boolean(saved) ||
              !Object.values(selected).length ||
              Object.values(selected).some((item) => !item.name.trim())
            }
            onClick={() => void confirm()}
          >
            Confirm evidence
          </button>
        </>
      )
    )
  }
  function renderStatus(): React.ReactNode {
    return (
      <>
        {pending.current && !saved && (
          <p>The reviewed source and selections are locked until confirmation is recovered.</p>
        )}
        <button disabled={reviewUnavailable()} onClick={() => void review()}>
          Review file evidence
        </button>
        {busy && (
          <p role="status">
            {confirming.current ? 'Saving reviewed evidence…' : 'Reading authorized file…'}
          </p>
        )}
        {error && <p role="alert">{error}</p>}
        {saved && <p role="status">{saved}</p>}
      </>
    )
  }
  return (
    <section aria-label="Local evidence review">
      <h3>Review local file evidence</h3>
      <p>
        {mode === 'Guide'
          ? 'Source files describe intended wiring. Review their pin and address evidence; this does not verify wiring or running software.'
          : 'Source evidence only. No wiring or runtime changes.'}
      </p>
      <FirmwareTelemetryOffer projectId={projectId} />
      {renderSourceChoices()}
      {renderStatus()}
      {renderProposal()}
    </section>
  )
}

function EvidenceResult({ proposal }: { proposal: ExtractionProposal }): React.JSX.Element {
  return (
    <div aria-label="Extracted evidence">
      {proposal.extraction.rows.length === 0 && (
        <p>No recognized wiring declarations in this file.</p>
      )}
      <ul>
        {proposal.extraction.rows.map((row, i) => (
          <li key={i}>
            <strong>{row.part_candidate ?? row.device ?? row.bus ?? 'Unresolved evidence'}</strong>
            <span>
              {' '}
              · {row.protocol ?? 'Protocol unknown'} · {row.address ?? 'Address unknown'}
            </span>
            <ul>
              {row.provenance.map((item, j) => (
                <li key={j}>
                  {item.pin_ref ?? item.source_ref}
                  {item.detail && <span> · {item.detail}</span>}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      {proposal.extraction.notes.map((note, i) => (
        <p key={i}>{note}</p>
      ))}
    </div>
  )
}

function reviewedSelections(
  selected: Record<number, { name: string; entity_id?: string }>
): ExtractionConfirmation['selections'] | null {
  const selections = Object.entries(selected).map(([index, selection]) => ({
    row_index: Number(index),
    ...selection,
    name: selection.name.trim()
  }))
  if (!selections.length || selections.some((selection) => !selection.name)) return null
  return selections
}
