// Shell chrome pieces, ported from TestDesign/app/shell-main.jsx: the topbar
// (project / screen / search / bell / sign out), the notifications popover,
// and the magic-moment toast.
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { dcol, SOLUS_DOMAINS } from '../../theme/tokens.constants'
import { relativeTime } from '../../lib/relativeTime'
import type { NotificationApi } from '../../lib/api/resources'
import { useShellStore } from './shellStore'
import type { Alert } from './workspaceData.constants'

export function TopBar({
  projectName,
  screenTitle,
  openCount,
  onBell,
  onSignOut
}: {
  projectName: string
  screenTitle: string
  openCount: number
  onBell: () => void
  onSignOut: () => void
}): React.JSX.Element {
  return (
    <div
      style={{
        height: 48,
        borderBottom: '1px solid var(--bd)',
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '0 16px',
        flexShrink: 0,
        position: 'relative',
        zIndex: 40,
        background: 'var(--bg)'
      }}
    >
      <span style={{ fontSize: 13, fontWeight: 600 }}>{projectName}</span>
      <span style={{ color: 'var(--mut)', fontSize: 12 }}>/</span>
      <span style={{ fontSize: 13, color: 'var(--mut)' }}>{screenTitle}</span>
      <div style={{ flex: 1 }} />
      <SearchBox />
      <BellButton openCount={openCount} onBell={onBell} />
      <Button kind="bare" size="sm" onClick={onSignOut}>
        Sign out
      </Button>
    </div>
  )
}

function SearchBox(): React.JSX.Element {
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

function BellButton({
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
      style={{ position: 'relative', cursor: 'pointer', padding: 6, color: 'var(--mut)' }}
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

export function NotifPopover({
  alerts,
  onOpen,
  onClose
}: {
  alerts: readonly Alert[]
  onOpen: (id: string) => void
  onClose: () => void
}): React.JSX.Element {
  return (
    <div
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
          <span onClick={onClose} style={{ color: 'var(--mut)', cursor: 'pointer' }}>
            <Icons.x size={12} />
          </span>
        </div>
        {alerts.map((a) => (
          <NotifRow key={a.id} alert={a} onOpen={onOpen} />
        ))}
        <div style={{ padding: '10px 14px', fontSize: 10.5, color: 'var(--mut)' }}>
          SOL checks every change across domains, automatically.
        </div>
      </Card>
    </div>
  )
}

function NotifRow({
  alert,
  onOpen
}: {
  alert: Alert
  onOpen: (id: string) => void
}): React.JSX.Element {
  const resolved = alert.state === 'resolved'
  return (
    <div
      id={`notif-${alert.id}`}
      onClick={() => onOpen(alert.id)}
      style={{
        display: 'flex',
        gap: 10,
        padding: '12px 14px',
        borderBottom: '1px solid var(--bd)',
        cursor: 'pointer',
        opacity: resolved ? 0.55 : 1
      }}
    >
      <span
        style={{
          color: resolved ? 'var(--ok)' : alert.sev === 'critical' ? 'var(--err)' : 'var(--warn)',
          marginTop: 1
        }}
      >
        {resolved ? <Icons.check size={14} /> : <Icons.warn size={14} />}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.4 }}>{alert.title}</div>
        <div style={{ display: 'flex', gap: 7, alignItems: 'center', marginTop: 4 }}>
          <Mono size={8.5} color={dcol(alert.fromD)}>
            {SOLUS_DOMAINS[alert.fromD].label}
          </Mono>
          <span style={{ color: 'var(--mut)', fontSize: 9 }}>→</span>
          <Mono size={8.5} color={dcol(alert.toD)}>
            {SOLUS_DOMAINS[alert.toD].label}
          </Mono>
          <span style={{ fontSize: 10, color: 'var(--mut)', whiteSpace: 'nowrap' }}>
            · {alert.actor} · {alert.time}
          </span>
        </div>
      </div>
      <Icons.arrowR size={12} />
    </div>
  )
}

/** Live notifications popover (API.md §2.1). Clicking a row marks it read. */
export function NotificationsPopover({
  items,
  onRead,
  onClose
}: {
  items: readonly NotificationApi[]
  onRead: (id: string) => void
  onClose: () => void
}): React.JSX.Element {
  return (
    <div
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
          <span onClick={onClose} style={{ color: 'var(--mut)', cursor: 'pointer' }}>
            <Icons.x size={12} />
          </span>
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
    <div style={{ position: 'fixed', top: 58, right: 16, width: 360, zIndex: 75 }}>
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
