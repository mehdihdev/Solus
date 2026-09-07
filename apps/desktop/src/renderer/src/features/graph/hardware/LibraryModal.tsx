// Flow 3 — Library (docs/wireflows/hardware-onboarding.md): search the Solus-curated
// parts and platforms, preview one definition, import a part under a robot's
// category or a platform as a new robot. Every imported value carries provenance
// `library`; a platform later seen on the wire raises a link suggestion, never a
// second robot. Definitions are the backend's claims, rendered as-is.
import { useEffect, useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { Spinner } from '../../../components/ui/Spinner'
import {
  ROBOT_CATEGORIES,
  ROBOT_CATEGORY_LABELS,
  getLibraryDefinition,
  importLibraryPart,
  importLibraryPlatform,
  searchLibrary,
  type LibraryDefinition,
  type LibraryHit,
  type LibraryKind,
  type LibraryPartDefinition,
  type LibraryPlatformDefinition,
  type LibraryPlatformPart,
  type RobotCategory
} from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { MODAL_INPUT_STYLE, ModalShell } from '../../workspace/modals'
import { LabeledSelect } from './AuthoredPartModal'
import { hardwareErrorText } from './detected'
import { CloseFooter } from './HardwareInfoModals'
import { HARDWARE_COPY } from './hardware.constants'

export interface LibraryModalProps {
  projectId: string
  mode: SolMode
  /** Existing physical_robot entities for the "Import into [robot]" target. */
  robots: readonly Entity[]
  onCreated: (entity: Entity) => void
  onClose: () => void
}

type Read<T> =
  | { phase: 'loading' }
  | { phase: 'error'; message: string }
  | { phase: 'ready'; value: T }
type Selection = { kind: LibraryKind; id: string }
type Imported = { text: string; suggestions: number }
type Outcome = ({ kind: 'status' } & Imported) | { kind: 'error'; message: string } | null

const SEARCH_DEBOUNCE_MS = 250
const NO_MATCH = 'Nothing in the library matches.'
const NO_ROBOT = 'Create a Physical Robot first (Add › Hardware › Authored).'
const MONO_STYLE = { fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)' } as const
const BODY_STYLE = { fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 } as const
const LABEL_STYLE = { display: 'block', marginTop: 12, fontSize: 11, color: 'var(--mut)' } as const
const LIST_STYLE = { listStyle: 'none', margin: '4px 0 0', padding: 0 } as const
const ROW_STYLE = { padding: '6px 0', borderTop: '1px solid var(--bd)' } as const
const CELL_STYLE = { textAlign: 'left', padding: '3px 8px 3px 0', fontWeight: 400 } as const
const PANE_STYLE = { minWidth: 0, maxHeight: 340, overflowY: 'auto' } as const
const HIT_STYLE = {
  display: 'block',
  width: '100%',
  textAlign: 'left',
  background: 'none',
  border: 0,
  padding: 0,
  cursor: 'pointer',
  color: 'var(--tx)'
} as const

const plural = (count: number, noun: string): string => `${count} ${noun}${count === 1 ? '' : 's'}`

/** One line of facts: category (part) or machine class + transport (platform), maker, driver. */
function facts(definition: LibraryDefinition): string {
  const driver = definition.driver_id ? `driver ${definition.driver_id}` : 'no driver'
  const head =
    definition.kind === 'part'
      ? [ROBOT_CATEGORY_LABELS[definition.category]]
      : [definition.machine_class, definition.transport]
  return [...head, definition.manufacturer, driver].filter(Boolean).join(' · ')
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

function settle<T>(promise: Promise<T>, isLive: () => boolean, set: (read: Read<T>) => void): void {
  promise.then(
    (value) => isLive() && set({ phase: 'ready', value }),
    (error: unknown) => isLive() && set({ phase: 'error', message: hardwareErrorText(error) })
  )
}

/** Debounced lexical search; the empty query (the seed on open) fires at once. A result is
 *  tagged with the query it answers, so "loading" is derived, never set. */
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

function useDefinition(
  projectId: string,
  selected: Selection | null
): Read<LibraryDefinition> | null {
  const [result, setResult] = useState<{
    selected: Selection
    read: Read<LibraryDefinition>
  } | null>(null)
  useEffect(() => {
    if (!selected) return
    let live = true
    settle(
      getLibraryDefinition(projectId, selected.kind, selected.id),
      () => live,
      (read) => setResult({ selected, read })
    )
    return () => {
      live = false
    }
  }, [projectId, selected])
  if (selected === null) return null
  return result?.selected === selected ? result.read : { phase: 'loading' }
}

/** One import call → busy flag and an honest outcome (the error text verbatim). */
function useImport(run: () => Promise<Imported>): {
  busy: boolean
  outcome: Outcome
  submit: () => Promise<void>
} {
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<Outcome>(null)
  const submit = async (): Promise<void> => {
    setBusy(true)
    setOutcome(null)
    try {
      setOutcome({ kind: 'status', ...(await run()) })
    } catch (failure) {
      setOutcome({ kind: 'error', message: hardwareErrorText(failure) })
    } finally {
      setBusy(false)
    }
  }
  return { busy, outcome, submit }
}

function HitGroup({
  label,
  hits,
  selected,
  onSelect
}: {
  label: string
  hits: readonly LibraryHit[]
  selected: Selection | null
  onSelect: (hit: LibraryHit) => void
}): React.JSX.Element | null {
  if (hits.length === 0) return null
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ ...MONO_STYLE, textTransform: 'uppercase' }}>{label}</div>
      <ul aria-label={label} style={LIST_STYLE}>
        {hits.map((hit) => (
          <li key={hit.id} style={ROW_STYLE}>
            <button
              type="button"
              aria-pressed={selected?.kind === hit.kind && selected.id === hit.id}
              onClick={() => onSelect(hit)}
              style={HIT_STYLE}
            >
              <span style={{ display: 'block', fontSize: 12.5 }}>{hit.name}</span>
              <span style={MONO_STYLE}>{hit.summary}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ResultsPane({
  hits,
  selected,
  onSelect
}: {
  hits: Read<LibraryHit[]>
  selected: Selection | null
  onSelect: (hit: LibraryHit) => void
}): React.JSX.Element {
  const ready = hits.phase === 'ready' ? hits.value : []
  const ofKind = (kind: LibraryKind): LibraryHit[] => ready.filter((hit) => hit.kind === kind)
  return (
    <div style={PANE_STYLE}>
      {hits.phase === 'loading' && <p role="status">Searching the library…</p>}
      {hits.phase === 'error' && <p role="alert">{hits.message}</p>}
      {hits.phase === 'ready' && ready.length === 0 && <p style={BODY_STYLE}>{NO_MATCH}</p>}
      <HitGroup label="Parts" hits={ofKind('part')} selected={selected} onSelect={onSelect} />
      <HitGroup
        label="Platforms"
        hits={ofKind('platform')}
        selected={selected}
        onSelect={onSelect}
      />
    </div>
  )
}

function OutcomeLine({ outcome }: { outcome: Outcome }): React.JSX.Element | null {
  if (!outcome) return null
  if (outcome.kind === 'error')
    return (
      <p role="alert" style={{ color: 'var(--err)', fontSize: 11.5 }}>
        {outcome.message}
      </p>
    )
  const n = outcome.suggestions
  const pending = n === 1 ? 'A link suggestion is pending' : `${n} link suggestions are pending`
  return (
    <p role="status" style={BODY_STYLE}>
      {outcome.text}
      {n > 0 && (
        <span style={{ display: 'block' }}>
          {pending} — Add › Hardware › Detected shows {n === 1 ? 'it' : 'them'}.
        </span>
      )}
    </p>
  )
}

function ImportButton({
  busy,
  label,
  onClick
}: {
  busy: boolean
  label: string
  onClick: () => Promise<void>
}): React.JSX.Element {
  return (
    <div style={{ marginTop: 12 }}>
      <Button kind="primary" size="sm" disabled={busy} onClick={() => void onClick()}>
        {busy ? <Spinner size={11} color="var(--acc-ink)" /> : label}
      </Button>
    </div>
  )
}

function SpecList({ rows }: { rows: readonly [string, string][] }): React.JSX.Element | null {
  if (rows.length === 0) return null
  return (
    <dl aria-label="Specs" style={{ margin: '10px 0 0', fontSize: 11.5 }}>
      {rows.map(([key, value]) => (
        <div key={key} style={{ display: 'flex', gap: 8, padding: '2px 0' }}>
          <dt style={{ ...MONO_STYLE, minWidth: 110 }}>{key}</dt>
          <dd style={{ margin: 0, color: 'var(--tx)' }}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function PartPreview({
  projectId,
  definition,
  robots,
  onCreated
}: {
  projectId: string
  definition: LibraryPartDefinition
  robots: readonly Entity[]
  onCreated: (entity: Entity) => void
}): React.JSX.Element {
  const [robotId, setRobotId] = useState(robots[0]?.id ?? '')
  const [category, setCategory] = useState<RobotCategory>(definition.category)
  const { busy, outcome, submit } = useImport(async () => {
    const out = await importLibraryPart(projectId, definition.id, { robot_id: robotId, category })
    onCreated(out.entity)
    return { text: 'Imported — 1 part', suggestions: 0 }
  })
  const robotName = robots.find((robot) => robot.id === robotId)?.name ?? 'robot'
  return (
    <>
      <SpecList rows={specRows(definition)} />
      {robots.length === 0 ? (
        <p style={BODY_STYLE}>{NO_ROBOT}</p>
      ) : (
        <>
          <LabeledSelect
            label="Robot"
            value={robotId}
            onChange={setRobotId}
            options={robots.map((robot) => ({ value: robot.id, label: robot.name }))}
          />
          <LabeledSelect
            label="Category"
            value={category}
            onChange={setCategory}
            options={ROBOT_CATEGORIES.map((id) => ({
              value: id,
              label: ROBOT_CATEGORY_LABELS[id]
            }))}
          />
          <OutcomeLine outcome={outcome} />
          <ImportButton busy={busy} label={`Import into ${robotName}`} onClick={submit} />
        </>
      )}
    </>
  )
}

/** The platform's slots, plus the gear-ratio table when any slot carries one. */
function PlatformParts({ parts }: { parts: readonly LibraryPlatformPart[] }): React.JSX.Element {
  const geared = parts.filter((slot) => slot.gear_ratio !== null)
  return (
    <>
      <ul aria-label="Platform parts" style={{ ...LIST_STYLE, marginTop: 10 }}>
        {parts.map((slot) => (
          <li key={slot.address} style={ROW_STYLE}>
            <span style={{ display: 'block', fontSize: 12.5, color: 'var(--tx)' }}>
              {slot.role}
            </span>
            <span style={MONO_STYLE}>
              {`${slot.part} @ ${slot.address}${slot.category ? ` · ${slot.category}` : ''}`}
            </span>
          </li>
        ))}
      </ul>
      {geared.length > 0 && (
        <table
          aria-label="Gear ratios"
          style={{ marginTop: 10, borderCollapse: 'collapse', fontSize: 11.5, color: 'var(--tx)' }}
        >
          <thead>
            <tr style={MONO_STYLE}>
              <th style={CELL_STYLE}>Role</th>
              <th style={CELL_STYLE}>Gear ratio</th>
            </tr>
          </thead>
          <tbody>
            {geared.map((slot) => (
              <tr key={slot.address}>
                <td style={CELL_STYLE}>{slot.role}</td>
                <td style={CELL_STYLE}>{slot.gear_ratio}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}

function PlatformPreview({
  projectId,
  definition,
  onCreated
}: {
  projectId: string
  definition: LibraryPlatformDefinition
  onCreated: (entity: Entity) => void
}): React.JSX.Element {
  const [name, setName] = useState('')
  const { busy, outcome, submit } = useImport(async () => {
    const out = await importLibraryPlatform(projectId, definition.id, name.trim() || undefined)
    onCreated(out.robot)
    return {
      text: `Imported — ${plural(out.part_ids.length, 'part')}`,
      suggestions: out.suggestion_ids.length
    }
  })
  // A platform import creates a robot: once it has, the form gives way to the outcome.
  const imported = outcome?.kind === 'status'
  return (
    <>
      {Object.keys(definition.params).length > 0 && (
        <div style={{ ...MONO_STYLE, marginTop: 4 }}>{JSON.stringify(definition.params)}</div>
      )}
      <PlatformParts parts={definition.parts} />
      {!imported && (
        <label style={LABEL_STYLE}>
          Robot name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={definition.name}
            maxLength={512}
            style={{ ...MODAL_INPUT_STYLE, marginTop: 4 }}
          />
        </label>
      )}
      <OutcomeLine outcome={outcome} />
      {!imported && <ImportButton busy={busy} label="Import as new robot" onClick={submit} />}
    </>
  )
}

function PreviewPane({
  definition,
  projectId,
  robots,
  onCreated
}: {
  definition: Read<LibraryDefinition> | null
  projectId: string
  robots: readonly Entity[]
  onCreated: (entity: Entity) => void
}): React.JSX.Element {
  if (definition === null) return <p style={BODY_STYLE}>Select a part or platform to preview it.</p>
  if (definition.phase === 'loading') return <p role="status">Reading the definition…</p>
  if (definition.phase === 'error') return <p role="alert">{definition.message}</p>
  const value = definition.value
  return (
    <section aria-label={value.name} style={{ marginTop: 8 }}>
      <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--tx)' }}>{value.name}</div>
      <div style={MONO_STYLE}>{facts(value)}</div>
      {value.notes && <p style={BODY_STYLE}>{value.notes}</p>}
      {value.kind === 'part' ? (
        <PartPreview
          key={value.id}
          projectId={projectId}
          definition={value}
          robots={robots}
          onCreated={onCreated}
        />
      ) : (
        <PlatformPreview
          key={value.id}
          projectId={projectId}
          definition={value}
          onCreated={onCreated}
        />
      )}
    </section>
  )
}

export function LibraryModal({
  projectId,
  mode,
  robots,
  onCreated,
  onClose
}: LibraryModalProps): React.JSX.Element {
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<Selection | null>(null)
  const hits = useSearch(projectId, query)
  const definition = useDefinition(projectId, selected)
  return (
    <ModalShell onClose={onClose} width={640}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Library</div>
      <div style={BODY_STYLE}>{HARDWARE_COPY.library[mode]}</div>
      <input
        type="search"
        aria-label="Search the library"
        placeholder="Search parts and platforms"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        autoFocus
        style={{ ...MODAL_INPUT_STYLE, marginTop: 12 }}
      />
      <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', gap: 16, marginTop: 4 }}>
        <ResultsPane
          hits={hits}
          selected={selected}
          onSelect={(hit) => setSelected({ kind: hit.kind, id: hit.id })}
        />
        <div style={PANE_STYLE}>
          <PreviewPane
            definition={definition}
            projectId={projectId}
            robots={robots}
            onCreated={onCreated}
          />
        </div>
      </div>
      <CloseFooter onClose={onClose} />
    </ModalShell>
  )
}
