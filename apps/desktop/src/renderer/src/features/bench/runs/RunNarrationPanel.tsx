import { useEffect, useRef, useState } from 'react'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../../graph/workspaceSession'
import { narrateRun, type RunNarration } from './runsApi'
type Props = { projectId: string; runId: string }
export function RunNarrationPanel(props: Props): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  return (
    <Panel
      key={`${props.projectId}:${props.runId}:${generation}`}
      {...props}
      generation={generation}
    />
  )
}
function Panel({
  projectId,
  runId,
  generation
}: Props & { generation: number }): React.JSX.Element {
  const [result, setResult] = useState<RunNarration | null>(null)
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(false)
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  const explain = async (): Promise<void> => {
    if (request.current) return
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    setError(false)
    try {
      const value = await narrateRun(projectId, runId, controller.signal)
      if (!controller.signal.aborted && generation === workspaceSessionGeneration())
        setResult(value)
    } catch {
      if (!controller.signal.aborted && generation === workspaceSessionGeneration()) setError(true)
    } finally {
      if (!controller.signal.aborted) {
        request.current = null
        setBusy(false)
      }
    }
  }
  return (
    <section aria-label="Finding explanation">
      <button disabled={busy} onClick={() => void explain()}>
        Explain findings
      </button>
      <p>
        Optional explanation uses your Solus model budget. Recorded evidence remains authoritative.
      </p>
      {busy && <p role="status">Explaining findings…</p>}
      {error && <p role="alert">Explanation unavailable; recorded findings remain available.</p>}
      {result && (
        <>
          <p>{result.reason}</p>
          {result.narration.map((text, index) => (
            <p key={index}>{text}</p>
          ))}
        </>
      )}
    </section>
  )
}
