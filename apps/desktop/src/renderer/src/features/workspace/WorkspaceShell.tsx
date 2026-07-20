// Workspace shell: icon rail, topbar (project / screen / search / bell),
// notifications popover, toast, mini orb, and the workspace screens plus the
// alert detail view. SOLUSDEV-152 removed the prototype demo data — the shell
// shows live API data or honest empty states, never fabricated robot data.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { SolOrb } from '../../components/ui/SolOrb'
import { Avatar } from '../../components/ui/Avatar'
import { Icons } from '../../components/ui/icons.constants'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { GraphScreen } from '../graph/GraphScreen'
import { AlertScreen } from '../graph/AlertScreen'
import { BenchScreen } from '../bench/BenchScreen'
import { SolScreen } from '../sol/SolScreen'
import { MiniOrb } from '../sol/MiniOrb'
import { TeamScreen } from '../team/TeamScreen'
import { BillingScreen } from '../billing/BillingScreen'
import { SettingsScreen } from '../settings/SettingsScreen'
import { HomeScreen } from './HomeScreen'
import { useMe, displayName } from './useMe'
import { useNotifications } from './useNotifications'
import { TopBar, OfflineNotifPopover, NotificationsPopover, ToastView } from './ShellChrome'
import { useShellStore, type MainScreen } from './shellStore'

type Route = { name: MainScreen } | { name: 'alert'; alertId: string }

/** Topbar title per screen (also the data-screen-label hook for tests). */
const SCREEN_TITLES: Readonly<Record<string, string>> = {
  home: 'Home',
  graph: 'Context Model',
  bench: 'Live Bench',
  sol: 'SOL',
  team: 'Team',
  billing: 'Billing',
  settings: 'Settings',
  alert: 'Alert'
}

/** Honest topbar fallback while no project is linked (SOLUSDEV-152). */
const NO_PROJECT_LABEL = 'No project'

export function WorkspaceShell(): React.JSX.Element {
  const navigate = useNavigate()
  const [route, setRoute] = useState<Route>({ name: 'home' })
  const [notifOpen, setNotifOpen] = useState(false)
  const signOut = useAuthStore((s) => s.signOut)
  const project = useWorkspaceStore((s) => s.project)
  const me = useMe()
  const notifs = useNotifications()
  const online = notifs.status === 'ready'

  const name = route.name

  const go = (screen: MainScreen): void => {
    useShellStore.getState().setLastMain(screen)
    setRoute({ name: screen })
    setNotifOpen(false)
  }
  const openProject = (p: { id: string; name: string }): void => {
    useWorkspaceStore.getState().setProject(p)
    go('graph')
  }
  const openAlert = (alertId: string): void => {
    setRoute({ name: 'alert', alertId })
    setNotifOpen(false)
  }
  const onSignOut = async (): Promise<void> => {
    await signOut()
    useWorkspaceStore.getState().reset()
    useShellStore.getState().reset()
    navigate('/')
  }

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        background: 'var(--bg)',
        color: 'var(--tx)',
        fontFamily: 'var(--font-ui)',
        overflow: 'hidden'
      }}
      onClick={() => notifOpen && setNotifOpen(false)}
    >
      <Rail name={name} go={go} userName={displayName(me.name, me.email)} />
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          minWidth: 0,
          position: 'relative'
        }}
      >
        <TopBar
          projectName={project?.name ?? NO_PROJECT_LABEL}
          screenTitle={SCREEN_TITLES[name] ?? ''}
          openCount={online ? notifs.unreadCount : 0}
          onBell={() => setNotifOpen((o) => !o)}
          onSignOut={() => void onSignOut()}
        />
        <VerifyEmailBanner />
        {notifOpen &&
          (online ? (
            <NotificationsPopover
              items={notifs.items}
              onRead={(id) => void notifs.markRead(id)}
              onReadAll={() => void notifs.markAllRead()}
              onClose={() => setNotifOpen(false)}
            />
          ) : (
            <OfflineNotifPopover onClose={() => setNotifOpen(false)} />
          ))}
        <div
          data-screen-label={SCREEN_TITLES[name]}
          style={{ flex: 1, display: 'flex', minHeight: 0, position: 'relative' }}
        >
          <ScreenView
            route={route}
            openProject={openProject}
            goBack={() => go(useShellStore.getState().lastMain)}
          />
        </div>
      </div>
      <ToastView
        onView={(alertId) => {
          if (alertId) openAlert(alertId)
          useShellStore.getState().clearToast()
        }}
      />
      <MiniOrb hidden={name === 'sol'} onClick={() => go('sol')} />
    </div>
  )
}

/** Persistent nudge for an unverified email (SOLUSDEV-82). Sensitive actions
 * (create team, invite, connect a source) are blocked server-side until the
 * address is confirmed; this explains why and offers a resend. Shows only when
 * the session explicitly reports the email as unverified. */
function VerifyEmailBanner(): React.JSX.Element | null {
  const user = useAuthStore((s) => s.user)
  const resend = useAuthStore((s) => s.resendConfirmation)
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)

  if (!user || user.emailVerified !== false) return null

  const onResend = async (): Promise<void> => {
    setBusy(true)
    await resend(user.email)
    setBusy(false)
    setSent(true)
  }

  return (
    <div
      role="alert"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 16px',
        background: 'color-mix(in srgb, var(--warn, #d9822b) 16%, var(--bg))',
        borderBottom: '1px solid var(--bd)',
        fontSize: 12.5
      }}
    >
      <Icons.mail size={14} />
      <span style={{ flex: 1 }}>
        Verify your email to create teams, invite members, and connect sources.
      </span>
      {sent ? (
        <span style={{ color: 'var(--mut)' }}>Verification email sent.</span>
      ) : (
        <button
          type="button"
          onClick={() => void onResend()}
          disabled={busy}
          style={{
            background: 'transparent',
            border: '1px solid var(--bd)',
            borderRadius: 4,
            color: 'var(--tx)',
            padding: '3px 10px',
            fontSize: 12,
            cursor: 'pointer'
          }}
        >
          {busy ? 'Sending…' : 'Resend email'}
        </button>
      )}
    </div>
  )
}

function ScreenView({
  route,
  openProject,
  goBack
}: {
  route: Route
  openProject: (project: { id: string; name: string }) => void
  goBack: () => void
}): React.JSX.Element | null {
  switch (route.name) {
    case 'home':
      return <HomeScreen onOpenProject={openProject} />
    case 'graph':
      return <GraphScreen />
    case 'bench':
      return <BenchScreen />
    case 'sol':
      return <SolScreen />
    case 'team':
      return <TeamScreen onOpenProject={openProject} />
    case 'billing':
      return <BillingScreen />
    case 'settings':
      return <SettingsScreen />
    case 'alert':
      return <AlertScreen onBack={goBack} />
  }
}

function Rail({
  name,
  go,
  userName
}: {
  name: string
  go: (screen: MainScreen) => void
  userName: string
}): React.JSX.Element {
  return (
    <div
      style={{
        width: 56,
        borderRight: '1px solid var(--bd)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '14px 0',
        gap: 8,
        flexShrink: 0,
        background: 'var(--sur)'
      }}
    >
      <div onClick={() => go('home')} style={{ marginBottom: 12, cursor: 'pointer' }}>
        <SolOrb size={24} />
      </div>
      <RailButton
        id="rail-home"
        icon={<Icons.box size={17} />}
        label="Home"
        active={name === 'home'}
        onClick={() => go('home')}
      />
      <RailButton
        id="rail-graph"
        icon={<Icons.graph size={17} />}
        label="Context Model"
        active={name === 'graph' || name === 'alert'}
        onClick={() => go('graph')}
      />
      <RailButton
        id="rail-bench"
        icon={<Icons.bench size={17} />}
        label="Live Bench"
        active={name === 'bench'}
        onClick={() => go('bench')}
      />
      <RailButton
        id="rail-sol"
        icon={<Icons.sol size={17} />}
        label="SOL"
        active={name === 'sol'}
        onClick={() => go('sol')}
      />
      <RailButton
        id="rail-team"
        icon={<Icons.team size={17} />}
        label="Team"
        active={name === 'team'}
        onClick={() => go('team')}
      />
      <div style={{ flex: 1 }} />
      <RailButton
        id="rail-billing"
        icon={<Icons.card size={17} />}
        label="Billing"
        active={name === 'billing'}
        onClick={() => go('billing')}
      />
      <RailButton
        id="rail-settings"
        icon={<Icons.gear size={17} />}
        label="Settings"
        active={name === 'settings'}
        onClick={() => go('settings')}
      />
      <div style={{ marginTop: 4 }}>
        <Avatar name={userName} size={26} />
      </div>
    </div>
  )
}

function RailButton({
  id,
  icon,
  label,
  active,
  onClick,
  badge
}: {
  id: string
  icon: React.ReactNode
  label: string
  active: boolean
  onClick: () => void
  badge?: boolean
}): React.JSX.Element {
  return (
    <div
      id={id}
      onClick={onClick}
      title={label}
      aria-label={label}
      style={{
        position: 'relative',
        width: 36,
        height: 36,
        borderRadius: 3,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        background: active ? 'color-mix(in srgb, var(--acc) 12%, transparent)' : 'transparent',
        color: active ? 'var(--acc)' : 'var(--mut)'
      }}
    >
      {icon}
      {badge && (
        <span
          style={{
            position: 'absolute',
            top: 2,
            right: 2,
            width: 7,
            height: 7,
            borderRadius: 99,
            background: 'var(--err)'
          }}
        />
      )}
      <span style={{ position: 'absolute', left: -9999 }}>{label}</span>
    </div>
  )
}
