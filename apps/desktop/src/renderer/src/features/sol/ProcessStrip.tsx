// SOLUSDEV-317: Running processes strip above the SOL composer (sol-page.md
// "Running processes strip"). One row per process SOL started on THIS machine
// for the open project: name or program, state, elapsed time, an Output toggle
// (bounded, keyboard-scrollable plain text, polled while open) and Stop — a
// direct user action through the owner-scoped route, no approval card.
// Process text is untrusted machine output: plain text only, never HTML.
import { useCallback, useEffect, useRef, useState } from 'react'
import type { CodeProcess } from '../../lib/api/resources.commands'
import './ProcessStrip.css'
import {
  MAX_CHUNK_CHARS,
  MAX_PROCESS_OUTPUT_CHARS,
  OUTPUT_POLL_MS,
  STOP_ERROR,
  elapsed,
  programName,
  stateLabel
} from './processStrip.constants'
import {
  REAL_PROCESS_DEPS,
  useCodeProcesses,
  type ProcessSnapshot,
  type ProcessStripDeps
} from './useCodeProcesses'

export type { ProcessStripDeps }

interface OutputScope {
  readonly projectId: string
  readonly machineId: string
  readonly processId: string
  readonly running: boolean
  readonly fetchOutput: ProcessStripDeps['getCodeProcessOutput']
}

/** Polls one process's output while mounted (open) and running; one final read
 *  when it stops running. Text is appended after the cursor, bounded. */
interface OutputText {
  readonly text: string
  readonly truncated: boolean
}

function useProcessOutput(scope: OutputScope): OutputText {
  const { projectId, machineId, processId, running, fetchOutput } = scope
  const [output, setOutput] = useState<OutputText>({ text: '', truncated: false })
  const cursor = useRef(0)
  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async (): Promise<void> => {
      try {
        const answer = await fetchOutput(projectId, processId, machineId, cursor.current)
        if (stopped) return
        const next = answer.chunks
          .filter((chunk) => chunk.seq > cursor.current)
          .map((chunk) => chunk.text.slice(0, MAX_CHUNK_CHARS))
          .join('')
        cursor.current = Math.max(cursor.current, answer.cursor)
        setOutput((previous) => {
          const joined = previous.text + next
          return {
            text: joined.slice(-MAX_PROCESS_OUTPUT_CHARS),
            truncated:
              previous.truncated || answer.truncated || joined.length > MAX_PROCESS_OUTPUT_CHARS
          }
        })
      } catch {
        // A missed poll is retried on the next tick; the row's state is the truth.
      }
      if (!stopped && running) timer = setTimeout(() => void poll(), OUTPUT_POLL_MS)
    }
    void poll()
    return () => {
      stopped = true
      if (timer !== undefined) clearTimeout(timer)
    }
  }, [projectId, machineId, processId, running, fetchOutput])
  return output
}

function ProcessOutputView(scope: OutputScope): React.JSX.Element {
  const { text, truncated } = useProcessOutput(scope)
  return (
    <div className="process-strip__output" role="group" aria-label="Process output">
      <pre tabIndex={0}>{text || 'No output yet.'}</pre>
      {truncated && <p>Earlier output was dropped — showing the most recent part.</p>}
    </div>
  )
}

function useStop(
  stopProcess: () => Promise<unknown>,
  onStopped: () => Promise<void>
): { busy: boolean; error: string | null; stop: () => Promise<void> } {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const stop = useCallback(async (): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      await stopProcess()
      await onStopped()
    } catch (thrown) {
      setError(thrown instanceof Error && thrown.message ? thrown.message : STOP_ERROR)
    } finally {
      setBusy(false)
    }
  }, [stopProcess, onStopped])
  return { busy, error, stop }
}

interface RowProps {
  readonly process: CodeProcess
  readonly readAt: number
  readonly projectId: string
  readonly machineId: string
  readonly deps: ProcessStripDeps
  readonly refresh: () => Promise<void>
}

function ProcessRow({
  process,
  readAt,
  projectId,
  machineId,
  deps,
  refresh
}: RowProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const id = process.process_id
  const stopProcess = useCallback(
    () => deps.stopCodeProcess(projectId, id, machineId),
    [deps, projectId, id, machineId]
  )
  const { busy, error, stop } = useStop(stopProcess, refresh)
  const running = process.state === 'running'
  return (
    <li className="process-strip__row">
      <div className="process-strip__line">
        <code className="process-strip__name">{programName(process)}</code>
        <span className="process-strip__state" data-state={process.state}>
          {stateLabel(process)}
        </span>
        <span className="process-strip__elapsed">{elapsed(process, readAt)}</span>
        <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          Output
        </button>
        {running && (
          <button type="button" disabled={busy} onClick={() => void stop()}>
            {busy ? 'Stopping…' : 'Stop'}
          </button>
        )}
      </div>
      {error !== null && (
        <p role="alert" className="process-strip__error">
          {error}
        </p>
      )}
      {open && (
        <ProcessOutputView
          projectId={projectId}
          machineId={machineId}
          processId={id}
          running={running}
          fetchOutput={deps.getCodeProcessOutput}
        />
      )}
    </li>
  )
}

function StripList({
  snapshot,
  ...rest
}: Omit<RowProps, 'process' | 'readAt'> & { snapshot: ProcessSnapshot }): React.JSX.Element {
  return (
    <section className="process-strip" aria-label="Running processes">
      <ul>
        {snapshot.processes.map((process) => (
          <ProcessRow
            key={process.process_id}
            process={process}
            readAt={snapshot.readAt}
            {...rest}
          />
        ))}
      </ul>
    </section>
  )
}

export interface ProcessStripProps {
  readonly projectId: string
  /** Changes when the transcript grows, so a just-started process appears now. */
  readonly refreshSignal?: unknown
  readonly deps?: ProcessStripDeps
}

export function ProcessStrip({
  projectId,
  refreshSignal,
  deps = REAL_PROCESS_DEPS
}: ProcessStripProps): React.JSX.Element | null {
  const { snapshot, machineId, refresh } = useCodeProcesses(projectId, deps, refreshSignal)
  if (snapshot === null || machineId === null) return null
  return (
    <StripList
      snapshot={snapshot}
      projectId={projectId}
      machineId={machineId}
      deps={deps}
      refresh={refresh}
    />
  )
}
