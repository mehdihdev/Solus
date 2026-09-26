import { useEffect, useRef, useState } from 'react'
import { Button } from '../../../components/ui/Button'
import {
  ARTIFACT_MAX_BYTES,
  listEntities,
  uploadArtifact,
  type BenchSession,
  type Entity
} from '../../../lib/api/resources'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../../graph/workspaceSession'
import { listRuns, startRun, stopRun, importRun, type RunSummary } from './runsApi'
import { RunEvidence } from './RunEvidence'
export interface RunsViewProps {
  projectId: string
  sessions: BenchSession[] | null
}
export function RunsView(props: RunsViewProps): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  return (
    <RunWorkspace key={`${props.projectId}:${generation}`} {...props} generation={generation} />
  )
}
function RunWorkspace({
  projectId,
  sessions,
  generation
}: RunsViewProps & { generation: number }): React.JSX.Element {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [robots, setRobots] = useState<Entity[]>([])
  const [query, setQuery] = useState('')
  const [robot, setRobot] = useState('')
  const [session, setSession] = useState('')
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [origin, setOrigin] = useState<'recorded' | 'synthetic'>('recorded')
  const [selected, setSelected] = useState('')
  const [cursor, setCursor] = useState<string | undefined>()
  const [next, setNext] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [robotError, setRobotError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const mounted = useRef(true)
  const pending = useRef(false)
  const sequence = useRef(0)
  const valid = (): boolean => mounted.current && workspaceSessionGeneration() === generation
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  useEffect(() => {
    let live = true
    void listEntities(projectId, { type: 'physical_robot', q: query, limit: 24 }).then(
      (rows) => {
        if (live) {
          setRobotError('')
          setRobots(
            rows
              .filter(
                (item) =>
                  item.project_id === projectId &&
                  item.type === 'physical_robot' &&
                  item.origin === 'manual' &&
                  item.source_id === null
              )
              .slice(0, 24)
          )
        }
      },
      () => {
        if (live) setRobotError('Saved robots could not be loaded.')
      }
    )
    return () => {
      live = false
    }
  }, [projectId, query])
  useEffect(() => {
    let live = true
    let fetching = false
    const controller = new AbortController()
    const refresh = async (): Promise<void> => {
      if (fetching || pending.current) return
      fetching = true
      const request = ++sequence.current
      try {
        const page = await listRuns(projectId, cursor, controller.signal)
        if (live && request === sequence.current) {
          setRuns(page.runs)
          setLoadError('')
          setNext(page.next_cursor)
          setLoaded(true)
        }
      } catch {
        if (live && request === sequence.current) {
          setLoadError('Runs could not be loaded. Use Refresh to retry.')
          setLoaded(true)
        }
      } finally {
        fetching = false
      }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 5000)
    return () => {
      live = false
      controller.abort()
      window.clearInterval(timer)
    }
  }, [projectId, cursor])
  const act = async (action: () => Promise<RunSummary>): Promise<void> => {
    if (pending.current || !valid()) return
    pending.current = true
    sequence.current += 1
    setBusy(true)
    setError('')
    try {
      const result = await action()
      if (valid()) setRuns((items) => [result, ...items.filter((item) => item.id !== result.id)])
    } catch (cause) {
      if (valid())
        setError(cause instanceof Error ? cause.message : 'The recording operation failed.')
    } finally {
      pending.current = false
      if (valid()) setBusy(false)
    }
  }
  const active = (sessions ?? []).filter(
    (item) => item.status === 'active' && item.provider === 'robot'
  )
  const eligible =
    active.some((item) => item.id === session) && robots.some((item) => item.id === robot)
  const importFile = async (): Promise<RunSummary> => {
    if (!file || file.size > ARTIFACT_MAX_BYTES || file.size === 0)
      throw new Error('Choose a nonempty JSON manifest of at most 8 MiB.')
    const uploaded = await uploadArtifact(projectId, file)
    if (!valid()) throw new Error('Workspace changed; import cancelled.')
    return importRun(projectId, {
      robot_id: robot,
      artifact_id: uploaded.artifact_id,
      name: name.trim(),
      origin
    })
  }
  const current = runs.find((item) => item.id === selected)
  return (
    <section aria-label="Bench runs" style={{ overflowY: 'auto', padding: 20, minHeight: 0 }}>
      <h2>Runs</h2>
      <p>
        Record an existing telemetry session. Recording does not start motion or connect hardware.
      </p>
      <label>
        Find run robot{' '}
        <input
          maxLength={120}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setRobot('')
          }}
        />
      </label>
      <label>
        Run robot{' '}
        <select value={robot} onChange={(event) => setRobot(event.target.value)}>
          <option value="">Choose a saved robot</option>
          {robots.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      {robots.length === 24 && (
        <p>Showing 24 matching robots. Narrow the search for another robot.</p>
      )}
      <label>
        Recording session{' '}
        <select value={session} onChange={(event) => setSession(event.target.value)}>
          <option value="">Choose an active saved-robot session</option>
          {active.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      {!active.length && (
        <p>
          No active saved-robot session is available. Use Manage connections to connect telemetry
          first.
        </p>
      )}
      <label>
        Run name{' '}
        <input maxLength={120} value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <Button
        disabled={!canStartRecording(busy, eligible, name)}
        onClick={() =>
          void act(() =>
            startRun(projectId, { robot_id: robot, session_id: session, name: name.trim() })
          )
        }
      >
        Start recording
      </Button>
      <RecordingImport
        origin={origin}
        setOrigin={setOrigin}
        setFile={setFile}
        disabled={!canImportRecording(busy, robots, robot, name, file)}
        onImport={() => void act(importFile)}
      />
      {busy && <p role="status">Saving recording…</p>}
      {[error, loadError, robotError].filter(Boolean).map((message) => (
        <p role="alert" key={message}>
          {message}
        </p>
      ))}
      <RunLoadStatus loaded={loaded} loadError={loadError} empty={!runs.length} />
      <Button
        kind="ghost"
        disabled={busy}
        onClick={() => {
          const request = ++sequence.current
          setCursor(undefined)
          setLoadError('')
          void listRuns(projectId).then(
            (page) => {
              if (valid() && request === sequence.current) {
                setRuns(page.runs)
                setLoadError('')
                setNext(page.next_cursor)
                setLoaded(true)
              }
            },
            () => {
              if (valid() && request === sequence.current)
                setLoadError('Runs could not be refreshed.')
            }
          )
        }}
      >
        Refresh runs
      </Button>
      <ul>
        {runs.map((run) => (
          <li key={run.id}>
            <button type="button" onClick={() => setSelected(run.id)}>
              {run.name}
            </button>{' '}
            · {run.origin} · {run.status} · {run.packet_count} packets · {run.drop_count} dropped{' '}
            {run.status === 'running' && (
              <Button
                disabled={busy}
                aria-label={`Stop ${run.name}`}
                onClick={() => void act(() => stopRun(projectId, run.id))}
              >
                Stop
              </Button>
            )}
          </li>
        ))}
      </ul>
      {next && (
        <Button
          disabled={busy}
          onClick={() => {
            setSelected('')
            setCursor(next)
          }}
        >
          Next runs
        </Button>
      )}
      {current && (
        <RunEvidence
          key={`${current.id}:${current.status}:${current.artifact_id ?? ''}`}
          projectId={projectId}
          run={current}
          runs={runs}
        />
      )}
    </section>
  )
}

function RecordingImport({
  origin,
  setOrigin,
  setFile,
  disabled,
  onImport
}: {
  origin: 'recorded' | 'synthetic'
  setOrigin: (value: 'recorded' | 'synthetic') => void
  setFile: (value: File | null) => void
  disabled: boolean
  onImport: () => void
}): React.JSX.Element {
  return (
    <details>
      <summary>Import a local recording</summary>
      <p>
        Choose a manifest file on this computer. Recorded origin is your declaration, not
        verification of live hardware.
      </p>
      <label>
        Run manifest file{' '}
        <input
          type="file"
          accept=".json,application/json"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
      </label>
      <label>
        Recording origin{' '}
        <select
          value={origin}
          onChange={(event) =>
            setOrigin(event.target.value === 'synthetic' ? 'synthetic' : 'recorded')
          }
        >
          <option value="recorded">Recorded</option>
          <option value="synthetic">Synthetic fixture</option>
        </select>
      </label>
      <Button disabled={disabled} onClick={onImport}>
        Import recording
      </Button>
    </details>
  )
}

function RunLoadStatus({
  loaded,
  loadError,
  empty
}: {
  loaded: boolean
  loadError: string
  empty: boolean
}): React.JSX.Element {
  return (
    <>
      {' '}
      {!loaded && <p role="status">Loading runs…</p>}
      {loaded && !loadError && empty && (
        <p>No runs have been captured or imported in this project.</p>
      )}
    </>
  )
}

function canStartRecording(busy: boolean, eligible: boolean, name: string): boolean {
  return !busy && eligible && Boolean(name.trim())
}
function canImportRecording(
  busy: boolean,
  robots: Entity[],
  robot: string,
  name: string,
  file: File | null
): boolean {
  return !busy && robots.some((item) => item.id === robot) && Boolean(name.trim()) && file !== null
}
