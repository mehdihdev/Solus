// SOLUSDEV-320 P5-T3d: the history node. It owns no rows — it is a view over
// GET /history (docs/api/solus.md §9), paged by cursor with "Load more".
import { useCallback, useEffect, useRef, useState } from 'react'
import { listHistory, type HistoryRow } from '../../lib/api/history'
import type { Page } from '../../lib/api/client'

const ACTOR_SHORT = 8
// `sync.completed` has no actor; edge decisions carry no domain.
const SYSTEM_ACTOR = 'system'

interface Props {
  projectId: string
  load?: (projectId: string, filters: { cursor?: string }) => Promise<Page<HistoryRow[]>>
}

type Status = 'loading' | 'ready' | 'failed'

function Row({ row }: { row: HistoryRow }): React.JSX.Element {
  return (
    <li>
      <span>{row.type}</span> {row.domain && <span>{row.domain}</span>}{' '}
      <span title={row.actor_id ?? SYSTEM_ACTOR}>
        {row.actor_id?.slice(0, ACTOR_SHORT) ?? SYSTEM_ACTOR}
      </span>{' '}
      <time dateTime={row.created_at}>{row.created_at}</time>{' '}
      <span>
        {row.entity_ids.length} {row.entity_ids.length === 1 ? 'entity' : 'entities'}
      </span>
      {row.why_ref && <span> why {row.why_ref}</span>}
    </li>
  )
}

export function HistoryList({ projectId, load = listHistory }: Props): React.JSX.Element {
  const [rows, setRows] = useState<HistoryRow[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [status, setStatus] = useState<Status>('loading')
  // A project switch mid-flight must not append the old project's page.
  const generation = useRef(0)
  // State is set only from promise callbacks (react-hooks/set-state-in-effect);
  // the mount site keys this list on the project, so a switch remounts it fresh.
  const fetchPage = useCallback(
    (after: string | null): void => {
      const ticket = ++generation.current
      load(projectId, after ? { cursor: after } : {}).then(
        (page) => {
          if (ticket !== generation.current) return
          setRows((previous) => (after ? [...previous, ...page.data] : page.data))
          setCursor(page.meta.next_cursor ?? null)
          setStatus('ready')
        },
        () => {
          if (ticket === generation.current) setStatus('failed')
        }
      )
    },
    [projectId, load]
  )
  useEffect(() => fetchPage(null), [fetchPage])
  if (status === 'failed') return <p role="status">Could not load history.</p>
  if (rows.length === 0)
    return <p role="status">{status === 'loading' ? 'Loading…' : 'Nothing recorded yet.'}</p>
  return (
    <div className="solus-history">
      <ul>
        {rows.map((row) => (
          <Row key={row.id} row={row} />
        ))}
      </ul>
      {cursor && (
        <button
          type="button"
          disabled={status === 'loading'}
          onClick={() => {
            setStatus('loading')
            fetchPage(cursor)
          }}
        >
          Load more
        </button>
      )}
    </div>
  )
}
