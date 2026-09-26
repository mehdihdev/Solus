import { useEffect, useRef, useState } from 'react'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../../graph/workspaceSession'
import {
  cadSources,
  startCadImport,
  cadImportStatus,
  type CadSource,
  type CadImportStatus
} from './cadApi'

interface Props {
  projectId: string
  robotId: string
  onImported: () => void
}

export function CadImport(props: Props): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  return (
    <ScopedCadImport
      key={JSON.stringify([props.projectId, props.robotId, generation])}
      {...props}
      generation={generation}
    />
  )
}

function ScopedCadImport({
  projectId,
  robotId,
  onImported,
  generation
}: Props & { generation: number }): React.JSX.Element {
  const [sources, setSources] = useState<CadSource[]>([])
  const [selected, setSelected] = useState('')
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [result, setResult] = useState<CadImportStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pollRetry, setPollRetry] = useState(0)
  const [pollFailed, setPollFailed] = useState(false)
  const controller = useRef<AbortController | null>(null)
  const sending = useRef(false)
  const source = sources.find((item) => item.id === selected)
  const busy = starting || result?.status === 'pending'

  useEffect(() => {
    const request = new AbortController()
    controller.current = request
    void cadSources(projectId, request.signal, true)
      .then((items) => {
        if (requestCurrent(request, generation)) setSources(items)
      })
      .catch(() => {
        if (requestCurrent(request, generation))
          setError('Connected CAD sources could not be loaded. Reopen Spawn to retry.')
      })
      .finally(() => {
        if (requestCurrent(request, generation)) setLoading(false)
      })
    return () => request.abort()
  }, [projectId, generation])

  useEffect(() => {
    if (result?.status !== 'pending') return
    const request = new AbortController()
    const importId = result.import_id
    let timer: ReturnType<typeof setTimeout> | undefined
    const current = (): boolean => requestCurrent(request, generation)
    async function poll(): Promise<void> {
      try {
        const next = await cadImportStatus(projectId, importId, request.signal)
        if (!current()) return
        if (next.status === 'pending') timer = setTimeout(() => void poll(), 1000)
        else {
          setResult(next)
          if (next.status === 'complete') onImported()
        }
      } catch {
        if (current()) {
          setPollFailed(true)
          setError('CAD import status is unavailable. The import may still be running.')
        }
      }
    }
    void poll()
    return () => {
      request.abort()
      clearTimeout(timer)
    }
  }, [projectId, generation, result, onImported, pollRetry])

  async function importCad(): Promise<void> {
    const request = controller.current
    if (
      !source?.observed_microversion ||
      !robotId ||
      !canStartImport(busy, sending.current, request, generation)
    )
      return
    sending.current = true
    setStarting(true)
    setError(null)
    setResult(null)
    setPollFailed(false)
    try {
      const next = await startCadImport(
        projectId,
        {
          robot_id: robotId,
          source_entity_id: source.id,
          expected_revision: source.observed_microversion
        },
        request.signal
      )
      if (!requestCurrent(request, generation)) return
      setResult(next)
      if (next.status === 'complete') onImported()
    } catch {
      if (requestCurrent(request, generation))
        setError('CAD import could not be started. Sync the selected source and try again.')
    } finally {
      sending.current = false
      if (requestCurrent(request, generation)) setStarting(false)
    }
  }

  return (
    <fieldset>
      <legend>Connected CAD</legend>
      {loading ? (
        <p>Loading synced CAD sources…</p>
      ) : sources.length === 0 ? (
        <p>No synced CAD sources yet. Connect and sync a CAD document in Home.</p>
      ) : (
        <label>
          Connected CAD source
          <select
            aria-label="Connected CAD source"
            disabled={busy}
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
          >
            <option value="">Select assembly or part</option>
            {sources.map((item) => (
              <option key={item.id} value={item.id} disabled={!item.observed_microversion}>
                {item.name}
                {item.observed_microversion ? '' : ' — sync required'}
              </option>
            ))}
          </select>
        </label>
      )}
      <p>
        Imports geometry from the selected revision. Models without verified motion joints remain
        static.
      </p>
      {source?.observed_microversion && (
        <p>
          Revision: <code>{source.observed_microversion}</code>
        </p>
      )}
      <button
        type="button"
        disabled={!robotId || !source?.observed_microversion || busy}
        onClick={() => void importCad()}
      >
        Import connected CAD
      </button>
      <ImportStatus
        starting={starting}
        result={result}
        error={error}
        pollFailed={pollFailed}
        onRetry={() => {
          setPollFailed(false)
          setError(null)
          setPollRetry((value) => value + 1)
        }}
      />
    </fieldset>
  )
}

function ImportStatus({
  starting,
  result,
  error,
  pollFailed,
  onRetry
}: {
  starting: boolean
  result: CadImportStatus | null
  error: string | null
  pollFailed: boolean
  onRetry: () => void
}): React.JSX.Element {
  return (
    <div aria-live="polite">
      {starting && <p>Starting CAD import…</p>}
      {result?.status === 'pending' && <p>CAD import in progress…</p>}
      {result?.status === 'complete' && <p>CAD model imported.</p>}
      <ImportFailure result={result} />
      {error && <p role="alert">{error}</p>}
      {pollFailed && (
        <button type="button" onClick={onRetry}>
          Check import status
        </button>
      )}
    </div>
  )
}

function requestCurrent(request: AbortController, generation: number): boolean {
  return !request.signal.aborted && workspaceSessionGeneration() === generation
}

function canStartImport(
  busy: boolean,
  sending: boolean,
  request: AbortController | null,
  generation: number
): request is AbortController {
  return !busy && !sending && request !== null && requestCurrent(request, generation)
}

function ImportFailure({ result }: { result: CadImportStatus | null }): React.JSX.Element | null {
  if (result?.status !== 'error') return null
  return (
    <p role="alert">
      CAD import failed.{' '}
      {result.reason ?? 'The source could not be converted. Sync it and try again.'}
    </p>
  )
}
