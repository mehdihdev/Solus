// SOLUSDEV-326 P3: the Hardware page's parts list (docs/wireflows/hardware-onboarding.md): the
// robots and parts the reader may see, grouped, each with a status derived from what is true
// now, and under them what the workspace describes and nothing has answered. "Add robot" and
// "Add" are the person's own action: the graph route directly, no card. Every name on show is
// someone's own text and prints as text.
import { Fragment, useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import {
  listExpectedParts,
  listHardwareParts,
  setInGraph,
  type DetectedDeviceOut,
  type ExpectedParts
} from '../../lib/api/hardware'
import { listEntities } from '../../lib/api/resources'
import { hardwareErrorText } from '../graph/hardware/hardwareErrorText'
import { useDeviceStore } from './deviceStore'
import {
  expectedKeys,
  groupParts,
  type PartGroup,
  type PartRow,
  type PartsData
} from './partsModel'
import { statusLabel, type PartStatus } from './partStatus'
import '../project/localFolder.css'
import './partsList.css'

export interface PartsListProps {
  projectId: string
  /** Changes when the page knows the hardware changed (a card was decided): read again. */
  refreshKey?: unknown
  /** Told after every read whether the list is empty ("No robot parts yet"). */
  onRead?: (empty: boolean) => void
}

interface Read {
  projectId: string
  data: PartsData
  expected: ExpectedParts
  /** The described rows' keys, in their order (`expectedKeys`). */
  expectedIds: readonly string[]
  ids: ReadonlySet<string>
  /** The rows this read brought that the one before it did not have. */
  fresh: ReadonlySet<string>
}

const COLUMNS = ['Part', 'What it is', 'Robot', 'In workspace graph', 'Status'] as const
const NO_DEVICES: readonly DetectedDeviceOut[] = []
const NO_ROBOT = 'none yet'
const DESCRIBED = 'Described in your workspace, not seen yet'
const NOT_SEEN: PartStatus = { kind: 'not_seen' }
const CLOCK_MS = 60_000
const isLastSeen = (status: PartStatus | null | undefined): boolean => status?.kind === 'last_seen'

/** Draws again each minute while `on` and the page is on show, so words that tell a time since
 * ("Last seen 2 minutes ago") stay true on a page nobody touches. */
function useMinuteClock(on: boolean): void {
  const [, tick] = useReducer((ticks: number) => ticks + 1, 0)
  useEffect(() => {
    if (!on) return
    let timer: ReturnType<typeof setInterval> | undefined
    const run = (): void => {
      if (document.visibilityState === 'visible') timer ??= setInterval(tick, CLOCK_MS)
    }
    const onVisibility = (): void => {
      clearInterval(timer)
      timer = undefined
      run()
      // Back on show after a rest: the words are true at once, not a minute later.
      if (timer) tick()
    }
    run()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [on])
}

async function readParts(projectId: string): Promise<Omit<Read, 'fresh'>> {
  const [robots, machines, parts, expected] = await Promise.all([
    listEntities(projectId, { type: 'physical_robot', limit: 100 }),
    listEntities(projectId, { type: 'machine', limit: 100 }),
    listHardwareParts(projectId),
    listExpectedParts(projectId)
  ])
  const expectedIds = expectedKeys(expected.expected)
  const ids = new Set([
    ...robots.map((robot) => robot.id),
    ...parts.map((part) => part.id),
    ...expectedIds
  ])
  return { projectId, data: { robots, machines, parts }, expected, expectedIds, ids }
}

function Status({ status }: { status: PartStatus }): React.JSX.Element {
  const pulse = status.kind === 'identifying' ? ' sol-pulse' : ''
  return (
    <span role="cell" className="hw-status">
      <span aria-hidden="true" className={`hw-dot hw-dot-${status.kind}${pulse}`} />
      {statusLabel(status)}
    </span>
  )
}

interface RowProps {
  id: string
  name: string
  what: string
  robot: string | null
  graph: string
  status: PartStatus
  fresh: boolean
  add?: React.ReactNode
}

function Row({ name, what, robot, graph, status, fresh, add }: RowProps): React.JSX.Element {
  return (
    <div role="row" className={`hw-grid hw-row${fresh ? ' local-row-in' : ''}`}>
      <span role="cell">
        <span className="hw-name">{name}</span>
        <span className="hw-robot-inline" aria-hidden="true">
          {robot ?? NO_ROBOT}
        </span>
      </span>
      <span role="cell">{what}</span>
      <span role="cell" className="hw-robot">
        {robot ?? NO_ROBOT}
      </span>
      <span role="cell" className="hw-graph">
        {graph}
        {add}
      </span>
      <Status status={status} />
    </div>
  )
}

const graphWords = (inGraph: boolean): string => (inGraph ? 'in graph' : 'not yet')

/** The row is on show (a later read may have taken a refused one away). */
const onShow = (groups: readonly PartGroup[], id: string): boolean =>
  groups.some((group) => group.id === id || group.rows.some((row) => row.id === id))

interface DescribedProps {
  read: Read
  open: boolean
  onToggle: () => void
}

/** What the workspace describes and nothing has answered: a line that opens into its rows. */
function Described({ read, open, onToggle }: DescribedProps): React.JSX.Element | null {
  const { expected } = read
  const described = expected.expected.length + expected.more
  if (!(described > 0)) return null
  const robotName = (id: string | null): string | null =>
    read.data.robots.find((robot) => robot.id === id)?.name ?? null
  return (
    <>
      <button
        type="button"
        className="interactive hw-described"
        aria-expanded={open}
        onClick={onToggle}
      >
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M3 1.5 L7 5 L3 8.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
        </svg>
        <span style={{ fontWeight: 600 }}>{DESCRIBED}</span>
        <span className="hw-faint">· {described}</span>
        <span className="hw-described-from">from {expected.sources.join(', ')}</span>
      </button>
      {open && (
        <div role="table" aria-label={DESCRIBED} className="hw-body" style={{ marginTop: 6 }}>
          {expected.expected.map((row, index) => {
            const id = read.expectedIds[index] ?? String(index)
            return (
              <Row
                key={id}
                id={id}
                name={row.name}
                what={row.what}
                robot={robotName(row.robot_id)}
                graph="described only"
                status={NOT_SEEN}
                fresh={read.fresh.has(id)}
              />
            )
          })}
          {expected.more > 0 && (
            <p className="hw-row hw-faint" style={{ margin: 0 }}>
              and {expected.more} more
            </p>
          )}
        </div>
      )}
    </>
  )
}

export function PartsList({ projectId, refreshKey, onRead }: PartsListProps): React.JSX.Element {
  const [read, setRead] = useState<Read | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [refusal, setRefusal] = useState<{ id: string; text: string } | null>(null)
  const [adding, setAdding] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const latest = useRef(0)
  const devices = useDeviceStore((state) =>
    state.projectId === projectId ? state.devices : NO_DEVICES
  )
  const left = useDeviceStore((state) => (state.projectId === projectId ? state.left : NO_DEVICES))

  const load = useCallback((): Promise<void> => {
    const mine = ++latest.current
    return readParts(projectId)
      .then((next) => {
        if (mine !== latest.current) return
        setFailure(null)
        setRead((was) => ({
          ...next,
          fresh:
            was?.projectId === projectId
              ? new Set([...next.ids].filter((id) => !was.ids.has(id)))
              : new Set()
        }))
      })
      .catch((error: unknown) => {
        if (mine === latest.current) setFailure(hardwareErrorText(error))
      })
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  const shown = read?.projectId === projectId ? read : null
  const { groups, count } = useMemo(
    () => (shown ? groupParts(shown.data, devices, left) : { groups: [], count: 0 }),
    [shown, devices, left]
  )
  const empty = shown ? groups.length === 0 : null
  useEffect(() => {
    if (empty !== null) onRead?.(empty)
  }, [empty, onRead])
  useMinuteClock(
    groups.some(
      (group) => isLastSeen(group.status) || group.rows.some((row) => isLastSeen(row.status))
    )
  )

  const add = (id: string): void => {
    setAdding(id)
    setRefusal(null)
    setInGraph(projectId, id, true)
      .then(load)
      // The server's own words: it names only the hardware this reader may see.
      .catch((error: unknown) => setRefusal({ id, text: hardwareErrorText(error) }))
      .finally(() => setAdding(null))
  }
  const groupRow = (group: PartGroup): React.JSX.Element => (
    <div
      role="row"
      className={`hw-grid hw-group${shown?.fresh.has(group.id) ? ' local-row-in' : ''}`}
    >
      <span role="cell" className="hw-group-name">
        {group.title} <span className="hw-faint">· {group.countLabel}</span>
      </span>
      <span role="cell" className="hw-graph">
        {group.inGraph === null ? '' : graphWords(group.inGraph)}
        {group.canAdd && (
          <Button
            kind="ghost"
            disabled={adding === group.id}
            onClick={() => add(group.id)}
            style={{ fontSize: 11, padding: '2px 8px' }}
          >
            Add robot
          </Button>
        )}
      </span>
      {group.status ? <Status status={group.status} /> : <span role="cell" />}
    </div>
  )
  const partRow = (row: PartRow): React.JSX.Element => (
    <Row
      {...row}
      graph={graphWords(row.inGraph)}
      fresh={!!shown?.fresh.has(row.id)}
      add={
        row.canAdd && (
          <Button
            kind="bare"
            disabled={adding === row.id}
            onClick={() => add(row.id)}
            style={{ color: 'var(--acc)', fontSize: 11, padding: '2px 4px' }}
          >
            Add
          </Button>
        )
      }
    />
  )

  return (
    <section>
      <h2 style={{ margin: '10px 0', fontSize: 13, fontWeight: 600 }}>
        Robot parts <span className="hw-faint">· {count}</span>
      </h2>
      {failure && (
        <p role="alert" className="hw-refusal">
          {failure}
        </p>
      )}
      <div role="table" aria-label="Robot parts">
        <div role="row" className="hw-grid hw-head">
          {COLUMNS.map((column) => (
            <span
              key={column}
              role="columnheader"
              className={column === 'Robot' ? 'hw-th hw-robot' : 'hw-th'}
            >
              {column}
            </span>
          ))}
        </div>
        {groups.length > 0 && (
          <div role="rowgroup" className="hw-body">
            {groups.flatMap((group) => [
              <Fragment key={group.id}>{groupRow(group)}</Fragment>,
              ...group.rows.map((row) => <Fragment key={row.id}>{partRow(row)}</Fragment>)
            ])}
          </div>
        )}
      </div>
      {/* Under the table, never in it: a rowgroup holds rows only. */}
      {/* The refused row may be gone: a later read may have taken it away. */}
      {refusal && onShow(groups, refusal.id) && (
        <p role="alert" className="hw-refusal">
          {refusal.text}
        </p>
      )}
      {empty && <div className="hw-empty">No robot parts yet</div>}
      {shown && <Described read={shown} open={open} onToggle={() => setOpen((was) => !was)} />}
    </section>
  )
}
