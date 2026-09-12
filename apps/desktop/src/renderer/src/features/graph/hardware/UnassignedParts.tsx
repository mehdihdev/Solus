// Unassigned parts (SOLUSDEV-250 P3, docs/wireflows/hardware-onboarding.md Flow 2): a
// collapsed disclosure over the parts no robot owns — connector parts and parts a deleted
// robot left behind — each attached one at a time under a robot's category. Nothing is
// read until the disclosure opens; names and types only, never an id.
import { useCallback, useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { Spinner } from '../../../components/ui/Spinner'
import type { Page } from '../../../lib/api/client'
import {
  ROBOT_CATEGORIES,
  ROBOT_CATEGORY_LABELS,
  attachParts,
  listUnassignedParts,
  type RobotCategory
} from '../../../lib/api/hardware'
import { HardwareSourcesPanel } from './HardwareSourcesPanel'
import { useHardwareGeneration } from './useHardwareGeneration'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { hardwareErrorText } from './detected'
import { HARDWARE_COPY } from './hardware.constants'
import { LabeledSelect } from './LabeledSelect'

export interface UnassignedPartsProps {
  projectId: string
  mode: SolMode
  robots: readonly Entity[]
  disabled: boolean
}

type Read = { phase: 'idle' | 'loading' | 'ready' } | { phase: 'error'; message: string }
type Reader = (projectId: string, cursor: string | null) => Promise<Page<Entity[]>>
interface Paged {
  parts: readonly Entity[]
  cursor: string | null
  read: Read
  load: (from: string | null) => void
  remove: (id: string) => void
}

const MONO_STYLE = { fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)' } as const
const BODY_STYLE = {
  fontSize: 12,
  color: 'var(--mut)',
  margin: '8px 0 0',
  lineHeight: 1.5
} as const
const ERROR_STYLE = { ...BODY_STYLE, color: 'var(--err)' } as const
const CATEGORY_OPTIONS = ROBOT_CATEGORIES.map((id) => ({
  value: id,
  label: ROBOT_CATEGORY_LABELS[id]
}))
const EMPTY = 'Nothing unassigned.'
const NO_ROBOT = 'No robot to add these to yet.'

/** One paged source: `load(null)` reads the first page, `load(cursor)` extends it. */
function usePaged(projectId: string, reader: Reader): Paged {
  const { generation } = useHardwareGeneration(projectId)
  const [state, setState] = useState<Pick<Paged, 'parts' | 'cursor' | 'read'>>({
    parts: [],
    cursor: null,
    read: { phase: 'idle' }
  })
  const load = useCallback(
    (from: string | null): void => {
      const ticket = generation.current
      setState((prev) => ({ ...prev, read: { phase: 'loading' } }))
      reader(projectId, from).then(
        (page) =>
          ticket === generation.current &&
          setState((prev) => ({
            parts: [
              ...new Map(
                (from ? [...prev.parts, ...page.data] : page.data).map((part) => [part.id, part])
              ).values()
            ],
            cursor: page.meta.has_next ? (page.meta.next_cursor ?? null) : null,
            read: { phase: 'ready' }
          })),
        (error: unknown) =>
          ticket === generation.current &&
          setState((prev) => ({
            ...prev,
            read: { phase: 'error', message: hardwareErrorText(error) }
          }))
      )
    },
    [projectId, reader, generation]
  )
  return {
    ...state,
    load,
    remove: (id) => setState((prev) => ({ ...prev, parts: prev.parts.filter((p) => p.id !== id) }))
  }
}

function PartRow({
  part,
  projectId,
  robots,
  disabled,
  onAttached
}: {
  part: Entity
  projectId: string
  robots: readonly Entity[]
  disabled: boolean
  onAttached: (id: string) => void
}): React.JSX.Element {
  const [robotChoice, setRobotChoice] = useState<string | null>(null)
  // ponytail: structure is the honest default for CAD/schematic parts; the user picks otherwise.
  const [category, setCategory] = useState<RobotCategory>('structure')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const robotId = robotChoice ?? robots[0]?.id ?? null
  const attach = async (): Promise<void> => {
    if (!robotId) return
    setBusy(true)
    setError(null)
    try {
      const result = await attachParts(projectId, robotId, { entity_ids: [part.id], category })
      if (result.attached.includes(part.id)) onAttached(part.id)
      else {
        setError('This part was not attached. Reload its current ownership and try again.')
        setBusy(false)
      }
    } catch (failure) {
      setError(hardwareErrorText(failure))
      setBusy(false)
    }
  }
  return (
    <li aria-label={part.name} style={{ padding: '6px 0', borderTop: '1px solid var(--bd)' }}>
      <span style={{ fontSize: 12.5, color: 'var(--tx)' }}>{part.name}</span>{' '}
      <span style={MONO_STYLE}>{part.type}</span>
      {robotId && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <LabeledSelect
            label="Part of"
            value={robotId}
            onChange={setRobotChoice}
            disabled={disabled}
            options={robots.map((robot) => ({ value: robot.id, label: robot.name }))}
          />
          <LabeledSelect
            label="Category"
            value={category}
            onChange={setCategory}
            disabled={disabled}
            options={CATEGORY_OPTIONS}
          />
          <Button
            kind="primary"
            size="sm"
            disabled={busy || disabled}
            onClick={() => void attach()}
          >
            {busy ? <Spinner size={11} color="var(--acc-ink)" /> : 'Add'}
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" style={ERROR_STYLE}>
          {error}
        </p>
      )}
    </li>
  )
}

function Group({
  heading,
  noun,
  paged,
  ...row
}: {
  heading: string
  noun: string
  paged: Paged
  projectId: string
  robots: readonly Entity[]
  disabled: boolean
}): React.JSX.Element | null {
  const { parts, cursor, read } = paged
  if (read.phase === 'idle') return null
  return (
    <div style={{ marginTop: 8 }}>
      {read.phase === 'error' && (
        <p role="alert" style={ERROR_STYLE}>
          {read.message}
        </p>
      )}
      {parts.length > 0 && (
        <>
          <div style={{ ...MONO_STYLE, textTransform: 'uppercase' }}>{heading}</div>
          <ul aria-label={heading} style={{ listStyle: 'none', margin: '4px 0 0', padding: 0 }}>
            {parts.map((part) => (
              <PartRow key={part.id} part={part} onAttached={paged.remove} {...row} />
            ))}
          </ul>
        </>
      )}
      {read.phase === 'loading' && <p role="status">Reading {noun}…</p>}
      {cursor && read.phase === 'ready' && (
        <Button kind="bare" size="sm" disabled={row.disabled} onClick={() => paged.load(cursor)}>
          Load more from {noun}
        </Button>
      )}
    </div>
  )
}

export function UnassignedParts({
  projectId,
  mode,
  robots,
  disabled
}: UnassignedPartsProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const sources = usePaged(projectId, listUnassignedParts)
  // Reads happen on open only — never on mount, never on a graph revision.
  const toggle = (): void => {
    setOpen(!open)
    if (open) return
    sources.load(null)
  }
  const settledEmpty = sources.read.phase === 'ready' && sources.parts.length === 0
  const row = { projectId, robots, disabled }
  return (
    <section aria-label="Unassigned parts" style={{ marginTop: 14 }}>
      <Button
        kind="bare"
        size="sm"
        aria-expanded={open}
        disabled={disabled}
        onClick={toggle}
        style={{ padding: '2px 0' }}
      >
        Unassigned parts
      </Button>
      {open && (
        <>
          <p style={BODY_STYLE}>{HARDWARE_COPY.unassigned[mode]}</p>
          {robots.length === 0 && <p style={BODY_STYLE}>{NO_ROBOT}</p>}
          <Group heading="Available parts" noun="unassigned parts" paged={sources} {...row} />
          {settledEmpty && <p style={BODY_STYLE}>{EMPTY}</p>}
          <HardwareSourcesPanel projectId={projectId} mode={mode} />
        </>
      )}
    </section>
  )
}
