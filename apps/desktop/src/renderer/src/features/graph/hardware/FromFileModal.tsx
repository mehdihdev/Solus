// Flow 2 — From a file (docs/wireflows/hardware-onboarding.md): parts from
// connected CAD / schematic / BOM sources that no robot owns, multi-selected
// and attached under a robot's category. Source identity and edges are untouched.
import { useCallback, useEffect, useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { Spinner } from '../../../components/ui/Spinner'
import {
  ROBOT_CATEGORIES,
  ROBOT_CATEGORY_LABELS,
  attachParts,
  listUnassignedParts,
  type RobotCategory
} from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { ModalShell } from '../../workspace/modals'
import { LabeledSelect } from './AuthoredPartModal'
import { hardwareErrorText } from './detected'
import { HARDWARE_COPY } from './hardware.constants'

export interface FromFileModalProps {
  projectId: string
  mode: SolMode
  robots: readonly Entity[]
  onClose: () => void
}

type Read = { phase: 'loading' } | { phase: 'error'; message: string } | { phase: 'ready' }
type Outcome = { kind: 'status'; text: string } | { kind: 'error'; message: string } | null

const MONO_STYLE = { fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)' } as const
const BODY_STYLE = { fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 } as const
const EMPTY_COPY = 'No unassigned parts from connected sources yet.'

function ReadStatus({ read, empty }: { read: Read; empty: boolean }): React.JSX.Element | null {
  if (read.phase === 'loading') return <p role="status">Reading unassigned parts…</p>
  if (read.phase === 'error') return <p role="alert">{read.message}</p>
  return empty ? <p style={BODY_STYLE}>{EMPTY_COPY}</p> : null
}

function PartsList({
  parts,
  selected,
  onToggle
}: {
  parts: readonly Entity[]
  selected: ReadonlySet<string>
  onToggle: (id: string) => void
}): React.JSX.Element | null {
  if (parts.length === 0) return null
  return (
    <ul
      aria-label="Unassigned parts"
      style={{
        listStyle: 'none',
        margin: '12px 0 0',
        padding: 0,
        maxHeight: 260,
        overflowY: 'auto'
      }}
    >
      {parts.map((part) => (
        <li key={part.id} style={{ padding: '6px 0', borderTop: '1px solid var(--bd)' }}>
          <label style={{ display: 'flex', gap: 10, alignItems: 'center', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={selected.has(part.id)}
              onChange={() => onToggle(part.id)}
            />
            <span style={{ flex: 1, minWidth: 0 }}>
              <span style={{ display: 'block', fontSize: 12.5, color: 'var(--tx)' }}>
                {part.name}
              </span>
              <span style={MONO_STYLE}>
                {part.type} · {part.source_key}
              </span>
            </span>
          </label>
        </li>
      ))}
    </ul>
  )
}

function RobotSelect({
  robots,
  value,
  onChange
}: {
  robots: readonly Entity[]
  value: string
  onChange: (value: string) => void
}): React.JSX.Element {
  if (robots.length === 0) {
    return <p style={BODY_STYLE}>Create a Physical Robot first (Add › Hardware › Authored).</p>
  }
  return (
    <LabeledSelect
      label="Robot"
      value={value}
      onChange={onChange}
      options={robots.map((robot) => ({ value: robot.id, label: robot.name }))}
    />
  )
}

function OutcomeLine({ outcome }: { outcome: Outcome }): React.JSX.Element | null {
  if (outcome === null) return null
  if (outcome.kind === 'status') return <p role="status">{outcome.text}</p>
  return (
    <p role="alert" style={{ color: 'var(--err)', fontSize: 11.5 }}>
      {outcome.message}
    </p>
  )
}

export function FromFileModal({
  projectId,
  mode,
  robots,
  onClose
}: FromFileModalProps): React.JSX.Element {
  const [read, setRead] = useState<Read>({ phase: 'loading' })
  const [parts, setParts] = useState<readonly Entity[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())
  const [robotId, setRobotId] = useState(robots[0]?.id ?? '')
  // ponytail: structure is the honest default for CAD/schematic parts; the user picks otherwise.
  const [category, setCategory] = useState<RobotCategory>('structure')
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<Outcome>(null)

  const load = useCallback(
    (from: string | null): Promise<void> =>
      listUnassignedParts(projectId, from).then(
        (page) => {
          setParts((prev) => (from ? [...prev, ...page.data] : page.data))
          setCursor(page.meta.has_next ? (page.meta.next_cursor ?? null) : null)
          setRead({ phase: 'ready' })
        },
        (error: unknown) => setRead({ phase: 'error', message: hardwareErrorText(error) })
      ),
    [projectId]
  )

  useEffect(() => {
    void load(null)
  }, [load])

  const toggle = (id: string): void =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (!next.delete(id)) next.add(id)
      return next
    })

  const attach = async (): Promise<void> => {
    if (!robotId || selected.size === 0) return
    setBusy(true)
    setOutcome(null)
    try {
      const out = await attachParts(projectId, robotId, { entity_ids: [...selected], category })
      const gone = new Set([...out.attached, ...out.skipped])
      setParts((prev) => prev.filter((part) => !gone.has(part.id)))
      setSelected(new Set())
      setOutcome({
        kind: 'status',
        text: `${out.attached.length} attached, ${out.skipped.length} already there`
      })
    } catch (failure) {
      setOutcome({ kind: 'error', message: hardwareErrorText(failure) })
    } finally {
      setBusy(false)
    }
  }

  const canAttach = robotId !== '' && selected.size > 0 && !busy
  return (
    <ModalShell onClose={onClose} width={520}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>From a file</div>
      <div style={BODY_STYLE}>{HARDWARE_COPY.file[mode]}</div>
      <ReadStatus read={read} empty={parts.length === 0} />
      <PartsList parts={parts} selected={selected} onToggle={toggle} />
      {cursor && (
        <Button kind="bare" size="sm" onClick={() => void load(cursor)}>
          Load more
        </Button>
      )}
      <RobotSelect robots={robots} value={robotId} onChange={setRobotId} />
      <LabeledSelect
        label="Category"
        value={category}
        onChange={setCategory}
        options={ROBOT_CATEGORIES.map((id) => ({ value: id, label: ROBOT_CATEGORY_LABELS[id] }))}
      />
      <OutcomeLine outcome={outcome} />
      <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
        <Button kind="primary" size="sm" disabled={!canAttach} onClick={() => void attach()}>
          {busy ? <Spinner size={11} color="var(--acc-ink)" /> : 'Add to robot'}
        </Button>
      </div>
    </ModalShell>
  )
}
