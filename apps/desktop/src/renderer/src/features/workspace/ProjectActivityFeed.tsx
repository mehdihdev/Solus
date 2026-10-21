// One project's activity, in full, inline in Home's Activity tab (SOLUSDEV-317;
// replaces the per-project dialog of SOLUSDEV-242). Server-filtered
// (`?project_id=`, API.md §2.2) so the total is the project's own and paging
// walks only its rows; a failed page keeps what is loaded (activity-feed.md).
import { useState } from 'react'
import type { ActivityApi } from '../../lib/api/resources'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { relativeTime } from '../../lib/relativeTime'
import { activityText } from '../team/activityText'
import { useProjectActivity } from './useProjectActivity'

export interface ProjectActivityFeedProps {
  project: { id: string; teamId: string }
}

/** One humanised row: what happened, and when. Payloads render as text. */
export function ActivityLine({ row }: { row: ActivityApi }): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        gap: 10,
        padding: '9px 0',
        borderTop: '1px solid var(--bd)',
        fontSize: 12.5
      }}
    >
      <span style={{ flex: 1, minWidth: 0 }}>{activityText(row)}</span>
      <span style={{ fontSize: 11, color: 'var(--mut)', whiteSpace: 'nowrap' }}>
        {relativeTime(row.created_at)}
      </span>
    </div>
  )
}

export function ProjectActivityFeed({ project }: ProjectActivityFeedProps): React.JSX.Element {
  const feed = useProjectActivity(project.teamId, project.id)
  const [loadingMore, setLoadingMore] = useState(false)
  const loadMore = async (): Promise<void> => {
    if (loadingMore) return
    setLoadingMore(true)
    try {
      await feed.loadMore()
    } finally {
      setLoadingMore(false)
    }
  }
  return (
    <Card pad={16}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
        <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
          PROJECT ACTIVITY
        </Mono>
        <div style={{ flex: 1 }} />
        {feed.status === 'ready' && (
          <Mono size={9} color="var(--mut)">
            {feed.total} {feed.total === 1 ? 'EVENT' : 'EVENTS'}
          </Mono>
        )}
      </div>
      <FeedBody feed={feed} />
      {feed.hasMore && (
        <div style={{ paddingTop: 12 }}>
          <Button kind="ghost" size="sm" disabled={loadingMore} onClick={() => void loadMore()}>
            {loadingMore ? 'Loading…' : 'Load more'}
          </Button>
        </div>
      )}
    </Card>
  )
}

function FeedBody({ feed }: { feed: ReturnType<typeof useProjectActivity> }): React.JSX.Element {
  if (feed.status === 'loading') return <Note>Loading activity…</Note>
  if (feed.status === 'offline')
    return <Note>Couldn&apos;t load this project&apos;s activity. Try again in a moment.</Note>
  if (feed.activity.length === 0) return <Note>No activity yet.</Note>
  return (
    <>
      {feed.activity.map((a) => (
        <ActivityLine key={a.id} row={a} />
      ))}
    </>
  )
}

function Note({ children }: { children: React.ReactNode }): React.JSX.Element {
  return <div style={{ fontSize: 12, color: 'var(--mut)', padding: '6px 0' }}>{children}</div>
}
