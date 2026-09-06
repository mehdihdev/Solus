// The team's humanised activity feed on Home (SOLUSDEV-244 / HOME H5) —
// extracted from the retired Team screen, unchanged in behaviour: a six-row
// preview with actor attribution, and the view-all dialog carrying the server
// total and cursor paging (docs/wireflows/activity-feed.md).
import { useState } from 'react'
import { Avatar } from '../../components/ui/Avatar'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { relativeTime } from '../../lib/relativeTime'
import type { ActivityApi, TeamMemberApi } from '../../lib/api/resources'
import { activityText, actorName } from '../team/activityText'
import { ActivityModal, ViewAllActivityButton } from '../team/ActivityModal'
import { ACTIVITY_PREVIEW_COUNT } from '../team/activityFeed.constants'

export interface TeamActivityPanelProps {
  activity: readonly ActivityApi[]
  members: readonly TeamMemberApi[]
  total: number
  hasMore: boolean
  onLoadMore: () => Promise<void>
}

function ActivityRow({
  row,
  members
}: {
  row: ActivityApi
  members: readonly TeamMemberApi[]
}): React.JSX.Element {
  const actor = actorName(row.actor_id, members)
  return (
    <div
      style={{
        display: 'flex',
        gap: 12,
        padding: '12px 16px',
        borderBottom: '1px solid var(--bd)'
      }}
    >
      <Avatar name={actor} size={26} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>
          <strong style={{ fontWeight: 600 }}>{actor}</strong> {activityText(row)}
        </div>
        <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 4 }}>
          {relativeTime(row.created_at)}
        </div>
      </div>
    </div>
  )
}

export function TeamActivityPanel({
  activity,
  members,
  total,
  hasMore,
  onLoadMore
}: TeamActivityPanelProps): React.JSX.Element {
  const [showAll, setShowAll] = useState(false)
  const preview = activity.slice(0, ACTIVITY_PREVIEW_COUNT)
  return (
    <Card pad={0}>
      <div
        style={{
          padding: '13px 16px',
          borderBottom: '1px solid var(--bd)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}
      >
        <Mono size={9.5}>TEAM ACTIVITY</Mono>
        <Mono size={9}>RECENT</Mono>
      </div>
      {activity.length === 0 && (
        <div style={{ padding: '18px 16px', fontSize: 12, color: 'var(--mut)' }}>
          No activity yet. Syncs, invites, and project changes will show up here.
        </div>
      )}
      {preview.map((row) => (
        <ActivityRow key={row.id} row={row} members={members} />
      ))}
      {total > ACTIVITY_PREVIEW_COUNT && (
        <ViewAllActivityButton total={total} onClick={() => setShowAll(true)} />
      )}
      {showAll && (
        <ActivityModal
          activity={activity}
          total={total}
          members={members}
          hasMore={hasMore}
          onLoadMore={onLoadMore}
          onClose={() => setShowAll(false)}
        />
      )}
    </Card>
  )
}
