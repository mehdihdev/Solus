// Search (SOLUSDEV-250 P3, docs/wireflows/hardware-onboarding.md Flow 3): one box over
// the curated library. Rows are flat — a platform adds as a new robot, a part adds to a
// robot in its default category — and a Details disclosure lazily reads the definition so
// nothing is hidden. Definitions are the backend's claims, rendered as-is.
import { useEffect, useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { Spinner } from '../../../components/ui/Spinner'
import {
  getLibraryDefinition,
  importLibraryPart,
  importLibraryPlatform,
  searchLibrary,
  type LibraryDefinition,
  type LibraryHit,
  type LibraryPartDefinition
} from '../../../lib/api/hardware'
import { createPhysicalRobot } from '../../../lib/api/physicalRobots'
import type { Entity } from '../../../lib/api/resources'
import { MODAL_INPUT_STYLE } from '../../workspace/modals'
import { hardwareErrorText } from './detected'
import { FIELD_CONTROL_STYLE, FIELD_LABEL_STYLE } from './hardware.constants'
import { LabeledSelect } from './LabeledSelect'

export interface HardwareSearchProps {
  projectId: string
  robots: readonly Entity[]
  onCreated: (entity: Entity) => void
  disabled: boolean
}

type Read<T> =
  | { phase: 'loading' }
  | { phase: 'error'; message: string }
  | { phase: 'ready'; value: T }
type Outcome = { kind: 'status'; text: string } | { kind: 'error'; message: string } | null

const SEARCH_DEBOUNCE_MS = 250
const NAME_MAX = 512
const PLACEHOLDER = 'Search parts and platforms — e.g. a servo model, a platform, a sensor'
const NO_MATCH = 'Nothing in the library matches.'
const SUGGESTION_PENDING = 'A link suggestion is pending — the device card offers it.'
const MONO_STYLE = { fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)' } as const
const BODY_STYLE = {
  fontSize: 12,
  color: 'var(--mut)',
  margin: '6px 0 0',
  lineHeight: 1.5
} as const
const ROW_STYLE = { padding: '8px 0', borderTop: '1px solid var(--bd)' } as const
const ACTION_STYLE = { display: 'flex', gap: 8, alignItems: 'flex-end', marginTop: 4 } as const
const INPUT_STYLE = {
  ...MODAL_INPUT_STYLE,
  marginTop: 4,
  padding: '6px 10px',
  fontSize: 12
} as const

function settle<T>(promise: Promise<T>, isLive: () => boolean, set: (read: Read<T>) => void): void {
  promise.then(
    (value) => isLive() && set({ phase: 'ready', value }),
    (error: unknown) => isLive() && set({ phase: 'error', message: hardwareErrorText(error) })
  )
}

/** Debounced lexical search; the empty query (the seed) fires at once. A result is tagged
 *  with the query it answers, so "loading" is derived, never set. */
function useSearch(projectId: string, query: string): Read<LibraryHit[]> {
  const [result, setResult] = useState<{ query: string; read: Read<LibraryHit[]> } | null>(null)
  useEffect(() => {
    let live = true
    const timer = setTimeout(
      () =>
        settle(
          searchLibrary(projectId, query),
          () => live,
          (read) => setResult({ query, read })
        ),
      query ? SEARCH_DEBOUNCE_MS : 0
    )
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [projectId, query])
  return result?.query === query ? result.read : { phase: 'loading' }
}

/** One write → busy flag and an honest outcome (the error text verbatim). */
function useAction(run: () => Promise<string>): {
  busy: boolean
  outcome: Outcome
  submit: () => void
} {
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<Outcome>(null)
  const submit = (): void => {
    setBusy(true)
    setOutcome(null)
    run()
      .then(
        (text) => setOutcome({ kind: 'status', text }),
        (failure: unknown) => setOutcome({ kind: 'error', message: hardwareErrorText(failure) })
      )
      .finally(() => setBusy(false))
  }
  return { busy, outcome, submit }
}

function OutcomeLine({ outcome }: { outcome: Outcome }): React.JSX.Element | null {
  if (!outcome) return null
  if (outcome.kind === 'error')
    return (
      <p role="alert" style={{ ...BODY_STYLE, color: 'var(--err)' }}>
        {outcome.message}
      </p>
    )
  return (
    <p role="status" style={BODY_STYLE}>
      {outcome.text}
    </p>
  )
}

function AddButton({
  busy,
  disabled,
  label,
  onClick
}: {
  busy: boolean
  disabled: boolean
  label: string
  onClick: () => void
}): React.JSX.Element {
  return (
    <Button kind="primary" size="sm" disabled={busy || disabled} onClick={onClick}>
      {busy ? <Spinner size={11} color="var(--acc-ink)" /> : label}
    </Button>
  )
}

function NameField({
  label,
  value,
  placeholder,
  onChange
}: {
  label: string
  value: string
  placeholder: string
  onChange: (value: string) => void
}): React.JSX.Element {
  return (
    <label style={{ ...FIELD_LABEL_STYLE, marginTop: 0, flex: 1 }}>
      {label}
      <input
        value={value}
        placeholder={placeholder}
        maxLength={NAME_MAX}
        onChange={(event) => onChange(event.target.value)}
        style={INPUT_STYLE}
      />
    </label>
  )
}

/** A platform → a new robot; the name is optional (empty → the definition's). */
function PlatformAction({
  hit,
  projectId,
  onCreated,
  disabled
}: {
  hit: LibraryHit
  projectId: string
  onCreated: (entity: Entity) => void
  disabled: boolean
}): React.JSX.Element {
  const [naming, setNaming] = useState(false)
  const [name, setName] = useState('')
  const { busy, outcome, submit } = useAction(async () => {
    const out = await importLibraryPlatform(projectId, hit.id, name.trim() || undefined)
    onCreated(out.robot)
    setNaming(false)
    return out.suggestion_ids.length > 0 ? SUGGESTION_PENDING : `Added ${out.robot.name}.`
  })
  return (
    <>
      {naming ? (
        <div style={ACTION_STYLE}>
          <NameField label="Robot name" value={name} placeholder={hit.name} onChange={setName} />
          <AddButton busy={busy} disabled={disabled} label="Add" onClick={submit} />
        </div>
      ) : (
        <div style={ACTION_STYLE}>
          <Button
            size="sm"
            disabled={disabled}
            aria-label={`Add ${hit.name} as new robot`}
            onClick={() => setNaming(true)}
          >
            Add as new robot
          </Button>
        </div>
      )}
      <OutcomeLine outcome={outcome} />
    </>
  )
}

/** A part → the chosen robot (the only one preselected); none → a new robot named here. */
function PartAction({
  hit,
  projectId,
  robots,
  onCreated,
  disabled
}: {
  hit: LibraryHit
  projectId: string
  robots: readonly Entity[]
  onCreated: (entity: Entity) => void
  disabled: boolean
}): React.JSX.Element {
  const [chosen, setChosen] = useState<string | null>(null)
  const [name, setName] = useState('')
  const robotId = chosen ?? robots[0]?.id ?? null
  const robotName = robots.find((robot) => robot.id === robotId)?.name
  const { busy, outcome, submit } = useAction(async () => {
    // ponytail: no robot yet → the part's robot is created here, named by the user; the
    // session's default-named create() cannot carry a name.
    const created = robotId
      ? null
      : await createPhysicalRobot(projectId, undefined, name.trim() || undefined)
    const out = await importLibraryPart(projectId, hit.id, {
      robot_id: created?.id ?? robotId ?? ''
    })
    onCreated(created ?? out.entity)
    return `Added ${out.entity.name}.`
  })
  return (
    <>
      <div style={ACTION_STYLE}>
        {robotId ? (
          <LabeledSelect
            label="Part of"
            value={robotId}
            onChange={setChosen}
            disabled={disabled}
            options={robots.map((robot) => ({ value: robot.id, label: robot.name }))}
          />
        ) : (
          <NameField label="New robot name" value={name} placeholder="Robot" onChange={setName} />
        )}
        <AddButton
          busy={busy}
          disabled={disabled}
          label={robotName ? `Add to ${robotName}` : 'Add to a new robot'}
          onClick={submit}
        />
      </div>
      <OutcomeLine outcome={outcome} />
    </>
  )
}

/** Key specs as rows: the definition's specs, then resolution, calibration and telemetry. */
function specRows(definition: LibraryPartDefinition): [string, string][] {
  const rows = Object.entries(definition.specs).map(([key, value]): [string, string] => [
    key,
    String(value)
  ])
  if (definition.resolution !== null) rows.push(['resolution', String(definition.resolution)])
  if (definition.calibration_mode !== null) rows.push(['calibration', definition.calibration_mode])
  if (definition.telemetry.length > 0) {
    const channels = definition.telemetry.map((t) =>
      t.unit ? `${t.quantity} (${t.unit})` : t.quantity
    )
    rows.push(['telemetry', channels.join(', ')])
  }
  return rows
}

function DefinitionFacts({ value }: { value: LibraryDefinition }): React.JSX.Element {
  const rows =
    value.kind === 'part'
      ? specRows(value)
      : value.parts.map((slot): [string, string] => [slot.role, `${slot.part} @ ${slot.address}`])
  const facts = [value.manufacturer, value.driver_id ? `driver ${value.driver_id}` : 'no driver']
  return (
    <div style={{ marginTop: 6 }}>
      <div style={MONO_STYLE}>{facts.filter(Boolean).join(' · ')}</div>
      {value.notes && <p style={BODY_STYLE}>{value.notes}</p>}
      {rows.length > 0 && (
        <ul
          aria-label={value.kind === 'part' ? 'Specs' : 'Platform parts'}
          style={{ listStyle: 'none', margin: '6px 0 0', padding: 0, fontSize: 11.5 }}
        >
          {rows.map(([key, text]) => (
            <li key={key} style={{ display: 'flex', gap: 8, padding: '2px 0' }}>
              <span style={{ ...MONO_STYLE, minWidth: 110 }}>{key}</span>
              <span style={{ color: 'var(--tx)' }}>{text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Lazily reads the definition the first time it opens. */
function Details({ projectId, hit }: { projectId: string; hit: LibraryHit }): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [read, setRead] = useState<Read<LibraryDefinition> | null>(null)
  const toggle = (): void => {
    setOpen(!open)
    if (read) return
    setRead({ phase: 'loading' })
    settle(getLibraryDefinition(projectId, hit.kind, hit.id), () => true, setRead)
  }
  return (
    <>
      <Button
        kind="bare"
        size="sm"
        aria-expanded={open}
        onClick={toggle}
        style={{ padding: '2px 0' }}
      >
        Details
      </Button>
      {open && read?.phase === 'loading' && <p role="status">Reading the definition…</p>}
      {open && read?.phase === 'error' && <p role="alert">{read.message}</p>}
      {open && read?.phase === 'ready' && <DefinitionFacts value={read.value} />}
    </>
  )
}

function SearchRow({
  hit,
  ...rest
}: {
  hit: LibraryHit
  projectId: string
  robots: readonly Entity[]
  onCreated: (entity: Entity) => void
  disabled: boolean
}): React.JSX.Element {
  return (
    <li aria-label={hit.name} style={ROW_STYLE}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
        <span style={{ fontSize: 12.5, color: 'var(--tx)' }}>{hit.name}</span>
        <span style={MONO_STYLE}>{hit.kind}</span>
      </div>
      <div style={MONO_STYLE}>{hit.summary}</div>
      {hit.kind === 'platform' ? (
        <PlatformAction hit={hit} {...rest} />
      ) : (
        <PartAction hit={hit} {...rest} />
      )}
      <Details projectId={rest.projectId} hit={hit} />
    </li>
  )
}

export function HardwareSearch(props: HardwareSearchProps): React.JSX.Element {
  const [query, setQuery] = useState('')
  const hits = useSearch(props.projectId, query)
  return (
    <div>
      <input
        type="search"
        aria-label="Search parts and platforms"
        placeholder={PLACEHOLDER}
        value={query}
        disabled={props.disabled}
        onChange={(event) => setQuery(event.target.value)}
        style={{ ...FIELD_CONTROL_STYLE, marginTop: 0 }}
      />
      {hits.phase === 'loading' && <p role="status">Searching the library…</p>}
      {hits.phase === 'error' && <p role="alert">{hits.message}</p>}
      {hits.phase === 'ready' && hits.value.length === 0 && <p style={BODY_STYLE}>{NO_MATCH}</p>}
      {hits.phase === 'ready' && hits.value.length > 0 && (
        <ul
          aria-label="Library results"
          style={{ listStyle: 'none', margin: '8px 0 0', padding: 0 }}
        >
          {hits.value.map((hit) => (
            <SearchRow key={`${hit.kind}:${hit.id}`} hit={hit} {...props} />
          ))}
        </ul>
      )}
    </div>
  )
}
