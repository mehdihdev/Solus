import { useEffect, useRef, useState } from 'react'
import { proposePartLinks, decidePartLink, type PartLink } from '../../../lib/api/partSuggestions'
import type { SolMode } from '../../../store/settingsStore'
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from '../workspaceSession'
type Props = {
  projectId: string
  partId: string
  robots: readonly { id: string; name: string }[]
  mode: SolMode
  onChanged: () => void
}
export function PartLinkSuggestions(props: Props): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  return (
    <Review
      key={`${props.projectId}:${props.partId}:${generation}`}
      {...props}
      generation={generation}
    />
  )
}
function Review({
  projectId,
  partId,
  robots,
  mode,
  onChanged,
  generation
}: Props & { generation: number }): React.JSX.Element {
  const [rows, setRows] = useState<PartLink[]>([]),
    [busy, setBusy] = useState(false),
    [frozen, setFrozen] = useState(false),
    [message, setMessage] = useState(''),
    [error, setError] = useState('')
  const pending = useRef(false),
    alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  const current = (): boolean => alive.current && generation === workspaceSessionGeneration()
  async function perform(accept?: boolean, row?: PartLink): Promise<void> {
    if (row && accept !== undefined) {
      await decidePartLink(projectId, row.id, accept)
      if (!current()) return
      setRows((old) => old.filter((item) => item.id !== row.id))
      setMessage(accept ? 'Part attached.' : 'Link declined.')
      if (accept) onChanged()
    } else {
      const found = await proposePartLinks(projectId, partId)
      if (!current()) return
      setRows(found)
      setMessage(found.length ? '' : 'No supported robot links.')
    }
  }
  async function run(accept?: boolean, row?: PartLink): Promise<void> {
    if (pending.current || frozen || !current()) return
    pending.current = true
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await perform(accept, row)
    } catch {
      if (current()) {
        setError(
          row
            ? 'Decision outcome could not be verified. Reload the graph before another decision.'
            : 'Robot links could not be checked. Try again.'
        )
        if (row) setFrozen(true)
      }
    } finally {
      pending.current = false
      if (current()) setBusy(false)
    }
  }
  return (
    <div aria-label="Part robot links">
      <button disabled={busy || frozen} onClick={() => void run()}>
        Find robot links
      </button>
      {rows.map((row) => {
        const name = robots.find((robot) => robot.id === row.robotId)?.name
        return (
          <div key={row.id}>
            <p>
              {name ?? 'Robot unavailable'} · {Math.round(row.confidence * 100)}%
            </p>
            {mode === 'Guide' && row.reason && <p>{row.reason}</p>}
            <button
              disabled={busy || frozen || !name}
              onClick={() => void run(true, row)}
              aria-label={`Accept link to ${name ?? 'robot'}`}
            >
              Accept
            </button>
            <button
              disabled={busy || frozen}
              onClick={() => void run(false, row)}
              aria-label={`Decline link to ${name ?? 'robot'}`}
            >
              Decline
            </button>
          </div>
        )
      })}
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  )
}
