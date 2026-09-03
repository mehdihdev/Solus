// Shell chrome pieces: the search box and bell (hosted by MenuBar since
// SOLUSDEV-235 moved the topbar into a title row + menu row), the live
// notifications popover, the honest offline popover, and the toast.
// SOLUSDEV-152 removed the demo-alert popover.
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { relativeTime } from '../../lib/relativeTime'
import type { NotificationApi } from '../../lib/api/resources'
import { useShellStore } from './shellStore'
import { useOfflineReason } from './workspaceOnline'

export function SearchBox(): React.JSX.Element {
  return (
    <div
      style={{
        width: 280,
        background: 'var(--sur)',
        border: '1px solid var(--bd)',
        borderRadius: 3,
        padding: '6px 11px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        color: 'var(--mut)'
      }}
    >
      <span style={{ fontSize: 12, display: 'inline-flex', gap: 8, alignItems: 'center' }}>
        <Icons.search size={12} /> Search nodes, nets, files…
      </span>
      <Mono size={9.5} style={{ textTransform: 'none' }}>
        ⌘K
      </Mono>
    </div>
  )
}

export function BellButton({
  openCount,
  onBell
}: {
  openCount: number
  onBell: () => void
}): React.JSX.Element {
  return (
    <div
      id="rail-bell"
      data-testid="rail-bell"
      onClick={(e) => {
        e.stopPropagation()
        onBell()
      }}
      className="interactive"
      style={{
        position: 'relative',
        cursor: 'pointer',
        padding: 6,
        borderRadius: 3,
        color: 'var(--mut)'
      }}
    >
      <Icons.bell size={17} />
      {openCount > 0 && (
        <span
          style={{
            position: 'absolute',
            top: 0,
            right: -2,
            minWidth: 14,
            height: 14,
            borderRadius: 99,
            background: 'var(--err)',
            color: '#fff',
            fontSize: 9,
            fontWeight: 700,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}
        >
          {openCount}
        </span>
      )}
    </div>
  )
}

/** Bell popover when the workspace isn't linked (dev bypass / unreachable
 *  API): an honest sign-in nudge — never fabricated alerts (SOLUSDEV-152). */
export function OfflineNotifPopover({ onClose }: { onClose: () => void }): React.JSX.Element {
  const reason = useOfflineReason()
  return (
    <div
      className="popover-in"
      style={{ position: 'absolute', top: 46, right: 12, width: 350, zIndex: 50 }}
      onClick={(e) => e.stopPropagation()}
    >
      <Card pad={0} style={{ boxShadow: '0 16px 50px rgba(0,0,0,0.5)' }}>
        <div
          style={{
            padding: '11px 14px',
            borderBottom: '1px solid var(--bd)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center'
          }}
        >
          <Mono size={9.5}>NOTIFICATIONS</Mono>
          <span
            aria-label="Close notifications"
            onClick={onClose}
            style={{ color: 'var(--mut)', cursor: 'pointer' }}
          >
            <Icons.x size={12} />
          </span>
        </div>
        <div style={{ padding: '16px 14px', fontSize: 11, color: 'var(--mut)', lineHeight: 1.5 }}>
          {reason === 'api_unreachable'
            ? "Solus can't reach its API right now — notifications will resume once it's back."
            : 'Sign in to Solus to see notifications about your teams and projects.'}
        </div>
      </Card>
    </div>
  )
}

/** Live notifications popover (API.md §2.1). Clicking a row marks it read;
 *  the header offers a bulk mark-all-read when anything is unread. */
export function NotificationsPopover({
  items,
  onRead,
  onReadAll,
  onClose
}: {
  items: readonly NotificationApi[]
  onRead: (id: string) => void
  onReadAll: () => void
  onClose: () => void
}): React.JSX.Element {
  const hasUnread = items.some((n) => !n.read_at)
  return (
    <div
      className="popover-in"
      style={{ position: 'absolute', top: 46, right: 12, width: 350, zIndex: 50 }}
      onClick={(e) => e.stopPropagation()}
    >
      <Card pad={0} style={{ boxShadow: '0 16px 50px rgba(0,0,0,0.5)' }}>
        <div
          style={{
            padding: '11px 14px',
            borderBottom: '1px solid var(--bd)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center'
          }}
        >
          <Mono size={9.5}>NOTIFICATIONS</Mono>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            {hasUnread && (
              <button
                type="button"
                onClick={onReadAll}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--acc)',
                  cursor: 'pointer',
                  fontFamily: 'var(--font-ui)',
                  fontSize: 11
                }}
              >
                Mark all read
              </button>
            )}
            <span onClick={onClose} style={{ color: 'var(--mut)', cursor: 'pointer' }}>
              <Icons.x size={12} />
            </span>
          </div>
        </div>
        {items.length === 0 && (
          <div style={{ padding: '16px 14px', fontSize: 11, color: 'var(--mut)' }}>
            You&apos;re all caught up.
          </div>
        )}
        {items.map((n) => (
          <div
            key={n.id}
            onClick={() => onRead(n.id)}
            className="interactive"
            style={{
              display: 'flex',
              gap: 10,
              padding: '12px 14px',
              borderBottom: '1px solid var(--bd)',
              cursor: 'pointer',
              opacity: n.read_at ? 0.55 : 1
            }}
          >
            {!n.read_at && (
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: 99,
                  background: 'var(--acc)',
                  marginTop: 5
                }}
              />
            )}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.4 }}>{n.title}</div>
              {n.body && (
                <div style={{ fontSize: 11, color: 'var(--mut)', marginTop: 2 }}>{n.body}</div>
              )}
              <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 3 }}>
                {relativeTime(n.created_at)}
              </div>
            </div>
          </div>
        ))}
      </Card>
    </div>
  )
}

export function ToastView({
  onView
}: {
  onView: (alertId?: string) => void
}): React.JSX.Element | null {
  const toast = useShellStore((s) => s.toast)
  const clearToast = useShellStore((s) => s.clearToast)
  if (!toast) return null
  const ok = toast.kind === 'ok'
  return (
    <div
      className="toast-in"
      style={{ position: 'fixed', top: 58, right: 16, width: 360, zIndex: 75 }}
    >
      <Card
        pad={14}
        style={{
          borderColor: ok
            ? 'color-mix(in srgb, var(--ok) 45%, var(--bd))'
            : 'color-mix(in srgb, var(--err) 50%, var(--bd))',
          boxShadow: '0 14px 44px rgba(0,0,0,0.55)',
          display: 'flex',
          gap: 11,
          alignItems: 'flex-start'
        }}
      >
        <span style={{ color: ok ? 'var(--ok)' : 'var(--err)', marginTop: 1 }}>
          {ok ? <Icons.check size={16} /> : <Icons.warn size={16} />}
        </span>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.4 }}>{toast.title}</div>
          <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 3, lineHeight: 1.5 }}>
            {toast.body}
          </div>
          {toast.action && (
            <Button
              kind="primary"
              size="sm"
              style={{ marginTop: 10 }}
              onClick={() => onView(toast.alertId)}
            >
              {toast.action}
            </Button>
          )}
        </div>
        <span onClick={clearToast} style={{ color: 'var(--mut)', cursor: 'pointer', padding: 2 }}>
          <Icons.x size={12} />
        </span>
      </Card>
    </div>
  )
}
