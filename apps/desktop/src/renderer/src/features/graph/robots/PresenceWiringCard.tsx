import { useEffect, useRef, useState } from 'react'
import type { PresenceProfileId } from '../../../lib/api/presence'
import {
  acceptWiring,
  proposeWiring,
  type WiringInput,
  type WiringProposal,
  type WiringRow
} from '../../../lib/api/presenceWiring'
import { listAllSources } from '../../../lib/api/resources'
import { listRuns } from '../../bench/runs/runsApi'
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from '../workspaceSession'
interface Props {
  projectId: string
  robotId: string
  brainId: string
  profileId: PresenceProfileId
  onAccepted: (id: string | null) => void
}
export function PresenceWiringCard(props: Props): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  return (
    <WiringCard
      key={`${generation}:${props.projectId}:${props.robotId}:${props.brainId}:${props.profileId}`}
      {...props}
      generation={generation}
    />
  )
}
function evidenceReference(
  mode: WiringInput['mode'],
  choice: string
): Pick<WiringInput, 'source_id' | 'run_id'> {
  if (mode === 'schematic') return { source_id: choice }
  if (mode === 'probe') return { run_id: choice }
  return {}
}
interface WiringViewProps {
  mode: WiringInput['mode'] | null
  rows: WiringRow[]
  choices: { id: string; name: string }[]
  choice: string
  proposal: WiringProposal | null
  accepted: boolean
  busy: boolean
  loading: boolean
  nextCursor: string | null
  loadMore: () => Promise<void>
  error: string | null
  valid: boolean
  chooseMode: (mode: WiringInput['mode']) => Promise<void>
  invalidate: () => void
  setChoice: (value: string) => void
  setRows: (rows: WiringRow[]) => void
  update: (index: number, patch: Partial<WiringRow>) => void
  review: () => Promise<void>
  accept: () => Promise<void>
}
function WiringCard(props: Props & { generation: number }): React.JSX.Element {
  return <WiringView {...useWiringController(props)} />
}
function useWiringController({
  projectId,
  robotId,
  brainId,
  profileId,
  onAccepted,
  generation
}: Props & { generation: number }): WiringViewProps {
  const [mode, setMode] = useState<WiringInput['mode'] | null>(null)
  const [rows, setRows] = useState<WiringRow[]>([{ channel: '', pin: '', kind: 'analog_input' }])
  const [choices, setChoices] = useState<{ id: string; name: string }[]>([]),
    [choice, setChoice] = useState('')
  const [proposal, setProposal] = useState<WiringProposal | null>(null),
    [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(false),
    [error, setError] = useState<string | null>(null)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const optionRequest = useRef<AbortController | null>(null)
  const seenCursors = useRef(new Set<string>())
  const optionEpoch = useRef(0)
  const epoch = useRef(0),
    alive = useRef(true),
    pending = useRef(false)
  const current = (ticket: number): boolean =>
    alive.current && epoch.current === ticket && generation === workspaceSessionGeneration()
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      optionRequest.current?.abort()
      epoch.current += 1
    }
  }, [])
  const invalidate = (): void => {
    epoch.current += 1
    pending.current = false
    setBusy(false)
    setProposal(null)
    setAccepted(false)
    setError(null)
    onAccepted(null)
  }
  const loadChoices = async (next: WiringInput['mode'], cursor?: string): Promise<void> => {
    optionRequest.current?.abort()
    const controller = new AbortController()
    optionRequest.current = controller
    setLoading(next !== 'typed')
    const ticket = ++optionEpoch.current
    const choicesCurrent = (): boolean =>
      alive.current && optionEpoch.current === ticket && generation === workspaceSessionGeneration()
    try {
      const page = await evidencePage(projectId, robotId, next, cursor, controller.signal)
      if (!choicesCurrent()) return
      if (cursor) seenCursors.current.add(cursor)
      setChoices((previous) => mergeChoices(cursor ? previous : [], page.choices))
      const repeated = page.cursor !== null && seenCursors.current.has(page.cursor)
      setNextCursor(repeated ? null : page.cursor)
      if (repeated)
        setError('Recorded run pagination repeated a cursor. Select this option again to refresh.')
    } catch {
      if (choicesCurrent())
        setError('Evidence choices unavailable. Select this option again to retry.')
    } finally {
      if (choicesCurrent()) {
        setLoading(false)
        optionRequest.current = null
      }
    }
  }
  const chooseMode = async (next: WiringInput['mode']): Promise<void> => {
    invalidate()
    setMode(next)
    setChoice('')
    setChoices([])
    setNextCursor(null)
    seenCursors.current.clear()
    await loadChoices(next)
  }
  const loadMore = async (): Promise<void> => {
    if (mode !== 'probe' || !nextCursor || optionRequest.current) return
    setError(null)
    await loadChoices('probe', nextCursor)
  }
  const update = (index: number, patch: Partial<WiringRow>): void => {
    invalidate()
    setRows(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }
  const wiring = rows.filter((row) => row.channel.trim() || row.pin.trim())
  const valid = wiring.every(
    (row) =>
      /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(row.channel) &&
      (row.kind === 'analog_input' ? /^A[0-9]+$/ : /^D[0-9]+$/).test(row.pin)
  )
  const review = async (): Promise<void> => {
    if (!mode || !valid || pending.current || (mode !== 'typed' && !choice)) return
    const ticket = ++epoch.current
    pending.current = true
    setBusy(true)
    setError(null)
    setProposal(null)
    setAccepted(false)
    onAccepted(null)
    try {
      const result = await proposeWiring(projectId, robotId, brainId, {
        profile_id: profileId,
        mode,
        wiring,
        ...evidenceReference(mode, choice)
      })
      if (current(ticket)) setProposal(result)
    } catch {
      if (current(ticket))
        setError(
          'Wiring review unavailable or evidence changed. Check selections and review again.'
        )
    } finally {
      if (current(ticket)) {
        pending.current = false
        setBusy(false)
      }
    }
  }
  const accept = async (): Promise<void> => {
    if (!proposal || pending.current || accepted) return
    const ticket = epoch.current
    pending.current = true
    setBusy(true)
    setError(null)
    try {
      const result = await acceptWiring(projectId, robotId, brainId, proposal)
      if (current(ticket)) {
        setAccepted(true)
        onAccepted(result.proposal_id)
      }
    } catch {
      if (current(ticket))
        setError(
          'Acceptance could not be verified. Retry this same proposal or review fresh evidence.'
        )
    } finally {
      if (current(ticket)) {
        pending.current = false
        setBusy(false)
      }
    }
  }
  return {
    mode,
    rows,
    choices,
    choice,
    proposal,
    accepted,
    busy,
    loading,
    nextCursor,
    loadMore,
    error,
    valid,
    chooseMode,
    invalidate,
    setChoice,
    setRows,
    update,
    review,
    accept
  }
}
function WiringView(props: WiringViewProps): React.JSX.Element {
  const { mode, chooseMode, busy, error, proposal, accepted } = props
  return (
    <section aria-label="Wiring evidence">
      <h4>What is wired to it?</h4>
      <p>
        Existing firmware may exist in a linked repository. A flash replaces it; review the full
        source and erase warning first.
      </p>
      <div>
        {(
          [
            ['typed', 'Tell me'],
            ['schematic', 'From the schematic'],
            ['probe', 'Let me look']
          ] as const
        ).map(([value, label]) => (
          <button key={value} aria-pressed={mode === value} onClick={() => void chooseMode(value)}>
            {label}
          </button>
        ))}
      </div>
      {mode === 'probe' && (
        <p>
          First prepare the probe, review its erase card, approve it and capture an actual run. Raw
          analog values and unknown I2C addresses do not identify attached parts.
        </p>
      )}
      {mode && <WiringInputs {...props} mode={mode} />}
      {busy && <p role="status">Checking wiring evidence…</p>}
      {error && <p role="alert">{error}</p>}
      {proposal && (
        <WiringResult proposal={proposal} busy={busy} accepted={accepted} accept={props.accept} />
      )}
      {accepted && <p role="status">Wiring accepted for firmware preparation.</p>}
    </section>
  )
}

function WiringInputs({
  mode,
  rows,
  choices,
  choice,
  loading,
  nextCursor,
  loadMore,
  busy,
  valid,
  invalidate,
  setChoice,
  setRows,
  update,
  review
}: WiringViewProps & { mode: WiringInput['mode'] }): React.JSX.Element {
  return (
    <>
      <WiringEvidencePicker
        {...{ mode, choices, choice, loading, nextCursor, loadMore, invalidate, setChoice }}
      />
      <p>
        Declare input channels explicitly. Pins use A0 for analog or D2 for digital. Leave blank to
        review evidence without declaring inputs.
      </p>
      {rows.map((row, i) => (
        <WiringRowFields
          key={i}
          row={row}
          i={i}
          update={update}
          remove={() => {
            invalidate()
            setRows(rows.filter((_, n) => n !== i))
          }}
        />
      ))}
      <button
        disabled={rows.length >= 16}
        onClick={() => {
          invalidate()
          setRows([...rows, { channel: '', pin: '', kind: 'analog_input' }])
        }}
      >
        Add input
      </button>
      <button
        disabled={busy || loading || !valid || (mode !== 'typed' && !choice)}
        onClick={() => void review()}
      >
        Review wiring
      </button>
    </>
  )
}

function WiringResult({
  proposal,
  busy,
  accepted,
  accept
}: {
  proposal: WiringProposal
  busy: boolean
  accepted: boolean
  accept: () => Promise<void>
}): React.JSX.Element {
  return (
    <div>
      <h4>Review wiring evidence</h4>
      {proposal.wiring.length === 0 && <p>No input channels declared.</p>}
      <ul>
        {proposal.wiring.map((row, i) => (
          <li key={i}>
            {row.channel} · {row.pin} · {row.kind}
          </li>
        ))}
      </ul>
      <ul>
        {proposal.observations.map((o, i) => (
          <li key={i}>
            {o.detail}
            {o.confidence !== null ? ` (confidence ${Math.round(o.confidence * 100)}%)` : ''}
          </li>
        ))}
      </ul>
      <ul>
        {proposal.unresolved.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
      <p>Accepting wiring records reviewed evidence; it does not flash or connect hardware.</p>
      <button disabled={busy || accepted} onClick={() => void accept()}>
        Accept wiring
      </button>
    </div>
  )
}

function WiringEvidencePicker({
  mode,
  choices,
  choice,
  loading,
  nextCursor,
  loadMore,
  invalidate,
  setChoice
}: Pick<
  WiringViewProps,
  'choices' | 'choice' | 'loading' | 'nextCursor' | 'loadMore' | 'invalidate' | 'setChoice'
> & {
  mode: WiringInput['mode']
}): React.JSX.Element {
  return (
    <>
      {mode !== 'typed' && (
        <label>
          {mode === 'schematic' ? 'Electrical source' : 'Captured probe run'}
          <select
            aria-label={mode === 'schematic' ? 'Electrical source' : 'Captured probe run'}
            value={choice}
            disabled={loading}
            onChange={(e) => {
              invalidate()
              setChoice(e.target.value)
            }}
          >
            <option value="">Choose evidence</option>
            {choices.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <RunPagination mode={mode} cursor={nextCursor} loading={loading} loadMore={loadMore} />
      {loading && <p role="status">Loading evidence…</p>}
      {!loading && mode !== 'typed' && choices.length === 0 && (
        <p>
          {mode === 'probe'
            ? emptyProbeChoices(nextCursor)
            : 'No connected electrical sources available.'}
        </p>
      )}
    </>
  )
}

function WiringRowFields({
  row,
  i,
  update,
  remove
}: {
  row: WiringRow
  i: number
  update: WiringViewProps['update']
  remove: () => void
}): React.JSX.Element {
  return (
    <fieldset>
      <legend>Input {i + 1}</legend>
      <label>
        Channel {i + 1}
        <input
          aria-label={`Channel ${i + 1}`}
          maxLength={64}
          value={row.channel}
          onChange={(e) => update(i, { channel: e.target.value })}
        />
      </label>
      <label>
        Pin {i + 1}
        <input
          aria-label={`Pin ${i + 1}`}
          maxLength={16}
          value={row.pin}
          onChange={(e) => update(i, { pin: e.target.value })}
        />
      </label>
      <label>
        Input kind {i + 1}
        <select
          aria-label={`Input kind ${i + 1}`}
          value={row.kind}
          onChange={(e) => update(i, { kind: e.target.value as WiringRow['kind'] })}
        >
          <option value="analog_input">Analog input</option>
          <option value="digital_input">Digital input</option>
        </select>
      </label>
      <button onClick={remove}>Remove input {i + 1}</button>
    </fieldset>
  )
}

interface EvidencePage {
  choices: { id: string; name: string }[]
  cursor: string | null
}
async function evidencePage(
  projectId: string,
  robotId: string,
  mode: WiringInput['mode'],
  cursor: string | undefined,
  signal: AbortSignal
): Promise<EvidencePage> {
  if (mode === 'schematic')
    return {
      choices: (await listAllSources(projectId))
        .filter((s) => s.status === 'connected' && ['kicad', 'altium'].includes(s.type))
        .map((s) => ({ id: s.id, name: s.name })),
      cursor: null
    }
  if (mode !== 'probe') return { choices: [], cursor: null }
  const page = await listRuns(projectId, cursor, signal)
  return {
    choices: page.runs
      .filter((r) => r.robot_id === robotId && r.status === 'completed')
      .map((r) => ({ id: r.id, name: `${r.name} (${r.origin})` })),
    cursor: page.next_cursor
  }
}
function mergeChoices(
  previous: EvidencePage['choices'],
  incoming: EvidencePage['choices']
): EvidencePage['choices'] {
  return [...new Map([...previous, ...incoming].map((choice) => [choice.id, choice])).values()]
}
function RunPagination({
  mode,
  cursor,
  loading,
  loadMore
}: {
  mode: WiringInput['mode']
  cursor: string | null
  loading: boolean
  loadMore: () => Promise<void>
}): React.JSX.Element | null {
  if (mode !== 'probe' || !cursor) return null
  return (
    <button disabled={loading} onClick={() => void loadMore()}>
      Load more recorded runs
    </button>
  )
}

function emptyProbeChoices(cursor: string | null): string {
  return cursor
    ? 'No matching completed runs on these pages. Load more recorded runs to check older captures.'
    : 'No completed runs available. Capture the probe first.'
}
