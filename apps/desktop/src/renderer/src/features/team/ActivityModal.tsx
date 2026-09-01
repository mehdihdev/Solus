// SOLUSDEV-233: the "View all activity" affordance and the full-feed dialog it
// opens. Shared by the Team screen (per-team feed with cursor paging) and the
// Home screen (merged cross-team feed). Rows carry actor attribution when a
// roster is available and degrade to plain text when it is not.
import { useState } from 'react'
import { Avatar } from '../../components/ui/Avatar'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { relativeTime } from '../../lib/relativeTime'
import type { ActivityApi, TeamMemberApi } from '../../lib/api/resources'
import { ModalShell } from '../workspace/modals'
import { activityText, actorName } from './activityText'

/** Footer affordance for the activity panels: opens the full-feed dialog. */
export function ViewAllActivityButton({
  total,
  onClick
}: {
  total: number
  onClick: () => void
}): React.JSX.Element {
  return (
    <button
      type="button"
      className="interactive"
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        width: '100%',
        textAlign: 'left',
        background: 'transparent',
        border: 'none',
        color: 'var(--acc)',
        cursor: 'pointer',
        fontFamily: 'var(--font-ui)',
        fontSize: 12.5,
        fontWeight: 600,
        padding: '12px 16px'
      }}
    >
      View all activity ({total}) <Icons.arrowR size={12} />
    </button>
  )
}

export interface ActivityModalProps {
  /** Every loaded row, newest first. */
  activity: ActivityApi[]
  /** Server-reported feed size — may exceed the loaded rows. */
  total: number
  /** Roster for actor attribution; omit for cross-team feeds (Home). */
  members?: readonly TeamMemberApi[]
  hasMore?: boolean
  onLoadMore?: () => Promise<void>
  onClose: () => void
}

/** Full activity feed in a dialog: internal scroll, optional Load more paging. */
export function ActivityModal({
  activity,
  total,
  members,
  hasMore = false,
  onLoadMore,
  onClose
}: ActivityModalProps): React.JSX.Element {
  const [loadingMore, setLoadingMore] = useState(false)
  const loadMore = async (): Promise<void> => {
    if (!onLoadMore || loadingMore) return
    setLoadingMore(true)
    try {
      await onLoadMore()
    } finally {
      setLoadingMore(false)
    }
  }
  return (
    <ModalShell onClose={onClose} width={560}>
      <div role="dialog" aria-label="All activity">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Mono size={9.5}>ALL ACTIVITY</Mono>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <Mono size={9} color="var(--mut)">
              {total} {total === 1 ? 'EVENT' : 'EVENTS'}
            </Mono>
            <button
              type="button"
              aria-label="Close"
              className="interactive"
              onClick={onClose}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--mut)',
                cursor: 'pointer',
                padding: 4,
                display: 'inline-flex'
              }}
            >
              <Icons.x size={13} />
            </button>
          </div>
        </div>
        <div style={{ maxHeight: '60vh', overflowY: 'auto', marginTop: 10 }}>
          {activity.length === 0 && (
            <div style={{ padding: '18px 4px', fontSize: 12, color: 'var(--mut)' }}>
              No activity yet.
            </div>
          )}
          {activity.map((a) => (
            <ActivityRow key={a.id} item={a} members={members} />
          ))}
          {hasMore && onLoadMore && (
            <div style={{ padding: '12px 0 2px' }}>
              <Button kind="ghost" size="sm" disabled={loadingMore} onClick={() => void loadMore()}>
                {loadingMore ? 'Loading…' : 'Load more'}
              </Button>
            </div>
          )}
          {!hasMore && activity.length < total && (
            <div style={{ padding: '12px 4px 2px', fontSize: 11, color: 'var(--mut)' }}>
              Showing the most recent {activity.length} of {total} events.
            </div>
          )}
        </div>
      </div>
    </ModalShell>
  )
}

function ActivityRow({
  item,
  members
}: {
  item: ActivityApi
  members?: readonly TeamMemberApi[]
}): React.JSX.Element {
  if (!members) {
    return (
      <div style={{ padding: '11px 4px', borderBottom: '1px solid var(--bd)' }}>
        <div style={{ fontSize: 12, lineHeight: 1.5 }}>{activityText(item)}</div>
        <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 3 }}>
          {relativeTime(item.created_at)}
        </div>
      </div>
    )
  }
  return (
    <div
      style={{ display: 'flex', gap: 12, padding: '12px 4px', borderBottom: '1px solid var(--bd)' }}
    >
      <Avatar name={actorName(item.actor_id, members)} size={26} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>
          <strong style={{ fontWeight: 600 }}>{actorName(item.actor_id, members)}</strong>{' '}
          {activityText(item)}
        </div>
        <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 4 }}>
          {relativeTime(item.created_at)}
        </div>
      </div>
    </div>
  )
}
