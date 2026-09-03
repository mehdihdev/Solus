// Workspace shell: title row (project pill), menu row (Solus · View · Robot ·
// Help + bridge / search / bell / sign out), icon rail, notifications popover,
// toast, mini orb, and the workspace screens plus the alert detail view.
// SOLUSDEV-235 replaced the breadcrumb topbar with the title + menu rows. SOLUSDEV-152 removed the prototype demo data — the shell
// shows live API data or honest empty states, never fabricated robot data.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
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
import { useValidateProject } from './useValidateProject'
import { ProjectOverview } from '../project/ProjectOverview'
import { SourcesScreen } from '../project/SourcesScreen'
import { StoreScreen } from '../extensions/StoreScreen'
import { useExtensionsStore } from '../extensions/extensionsStore'
import { HomeScreen } from './HomeScreen'
import { ProjectSwitcher } from './ProjectSwitcher'
import { useMe, displayName } from './useMe'
import { useNotifications } from './useNotifications'
import { OfflineNotifPopover, NotificationsPopover, ToastView } from './ShellChrome'
import { TitleBar } from './TitleBar'
import { MenuBar } from './MenuBar'
import { useShellStore, type MainScreen } from './shellStore'
import { useFocusStore } from './focusStore'

type Route = { name: MainScreen } | { name: 'alert'; alertId: string }

/** Screen labels (the data-screen-label hook for tests; the topbar breadcrumb is gone — SOLUSDEV-235). */
const SCREEN_TITLES: Readonly<Record<string, string>> = {
  home: 'Home',
  overview: 'Overview',
  graph: 'Context Model',
  sources: 'Sources',
  bench: 'Live Bench',
  sol: 'SOL',
  team: 'Team',
  store: 'Store',
  billing: 'Billing',
  settings: 'Settings',
  alert: 'Alert'
}

export function WorkspaceShell(): React.JSX.Element {
  const navigate = useNavigate()
  const [route, setRoute] = useState<Route>({ name: 'home' })
  const [notifOpen, setNotifOpen] = useState(false)
  const signOut = useAuthStore((s) => s.signOut)
  const me = useMe()
  const notifs = useNotifications()
  const online = notifs.status === 'ready'

  const name = route.name

  const go = (screen: MainScreen): void => {
    useShellStore.getState().setLastMain(screen)
    // The rail's Store button always lands on the catalog, not a stale detail page.
    if (screen === 'store') useExtensionsStore.getState().select(null)
    setRoute({ name: screen })
    setNotifOpen(false)
  }
  // Reactive: the bridge pill re-scopes when the topbar switcher changes the
  // project (merge fix — SOLUSDEV-164 moved the current project into the store).
  const project = useWorkspaceStore((s) => s.project)
  // The persisted project id names a server row that can disappear under us.
  // Confirm it once, so a dead id drops us to Home instead of 404ing every
  // project-scoped screen with no way back.
  useValidateProject()
  const openProject = (p: { id: string; name: string }): void => {
    useWorkspaceStore.getState().setProject(p)
    // Entity ids are project-scoped, so the focus cache must not survive the switch (WS-01).
    useFocusStore.getState().clearProject()
    // Opening a project from Home/Team lands on the project hub (SOLUSDEV-164)
    // — an orienting overview — rather than the Context Model canvas.
    go('overview')
  }
  const switchProject = (p: { id: string; name: string }): void => {
    // Switching from the topbar only re-scopes the CURRENT screen to the new
    // project — it must not navigate away and interrupt the user's flow.
    useWorkspaceStore.getState().setProject(p)
    useFocusStore.getState().clearProject()
    // A detail page belongs to the project it was opened in (SOLUSDEV-235).
    useExtensionsStore.getState().select(null)
    setNotifOpen(false)
  }
  const openAlert = (alertId: string): void => {
    setRoute({ name: 'alert', alertId })
    setNotifOpen(false)
  }
  const onSignOut = async (): Promise<void> => {
    await signOut()
    useWorkspaceStore.getState().reset()
    useShellStore.getState().reset()
    // The focus cache holds another user's entity names and properties in renderer memory. On a
    // shared workstation, leaving it would let the NEXT user read them with no request and no
    // authorization check (WS-01).
    useFocusStore.getState().reset()
    // Per-project install state is this user's workspace configuration; on a shared
    // workstation it must not outlive the session (same reasoning as WS-01).
    useExtensionsStore.getState().reset()
    navigate('/')
  }

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--bg)',
        color: 'var(--tx)',
        fontFamily: 'var(--font-ui)',
        overflow: 'hidden'
      }}
      onClick={() => notifOpen && setNotifOpen(false)}
    >
      <TitleBar>
        <ProjectSwitcher onSwitch={switchProject} onHome={() => go('home')} />
      </TitleBar>
      <div style={{ position: 'relative', flexShrink: 0 }}>
        <MenuBar
          activeScreen={name}
          hasProject={project !== null}
          openCount={online ? notifs.unreadCount : 0}
          projectId={project?.id ?? null}
          onNavigate={go}
          onSignOut={() => void onSignOut()}
          onBell={() => setNotifOpen((o) => !o)}
        />
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
      </div>
      <VerifyEmailBanner />
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        <Rail name={name} go={go} userName={displayName(me.name, me.email)} />
        <div
          data-screen-label={SCREEN_TITLES[name]}
          style={{ flex: 1, display: 'flex', minHeight: 0, minWidth: 0, position: 'relative' }}
        >
          <ScreenView
            route={route}
            openProject={openProject}
            navigate={go}
            goBack={() => go(useShellStore.getState().lastMain)}
          />
        </div>
      </div>
      <ToastView
        onView={(alertId) => {
          const screen = useShellStore.getState().toast?.screen
          if (alertId) openAlert(alertId)
          else if (screen) go(screen)
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

/** Screens that take no props, keyed by name (keeps ScreenView's branching low). */
const SIMPLE_SCREENS: Readonly<Record<string, () => React.JSX.Element>> = {
  graph: GraphScreen,
  sources: SourcesScreen,
  store: StoreScreen,
  sol: SolScreen,
  billing: BillingScreen,
  settings: SettingsScreen
}

function ScreenView({
  route,
  openProject,
  navigate,
  goBack
}: {
  route: Route
  openProject: (project: { id: string; name: string }) => void
  navigate: (screen: MainScreen) => void
  goBack: () => void
}): React.JSX.Element | null {
  const screen = ((): React.JSX.Element | null => {
    switch (route.name) {
      case 'home':
        return <HomeScreen onOpenProject={openProject} />
      case 'overview':
        return <ProjectOverview onNavigate={navigate} />
      case 'bench':
        // Bench needs navigation for its "Connect a device" path (SOLUSDEV-72).
        return <BenchScreen onNavigate={navigate} />
      case 'team':
        return <TeamScreen onOpenProject={openProject} />
      case 'alert':
        return <AlertScreen onBack={goBack} />
      default: {
        const Screen = SIMPLE_SCREENS[route.name]
        return Screen ? <Screen /> : null
      }
    }
  })()
  if (!screen) return null
  // SOLUSDEV-233: every screen switch enters with the app's fade-rise — keyed
  // by route so the animation replays per navigation (CSS-only, reduced-motion
  // guarded in main.css).
  return (
    <div
      key={route.name === 'alert' ? `alert-${route.alertId}` : route.name}
      className="screen-in"
      style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}
    >
      {screen}
    </div>
  )
}

interface RailItem {
  screen: MainScreen
  icon: React.ReactNode
  label: string
}

/** Top rail: Home + the project-scoped screens (Overview → Sources) in flow order. */
const RAIL_TOP: readonly RailItem[] = [
  { screen: 'home', icon: <Icons.box size={17} />, label: 'Home' },
  { screen: 'overview', icon: <Icons.spark size={17} />, label: 'Overview' },
  { screen: 'graph', icon: <Icons.graph size={17} />, label: 'Context Model' },
  { screen: 'sources', icon: <Icons.link size={17} />, label: 'Sources' },
  { screen: 'bench', icon: <Icons.bench size={17} />, label: 'Live Bench' },
  { screen: 'sol', icon: <Icons.sol size={17} />, label: 'SOL' },
  { screen: 'team', icon: <Icons.team size={17} />, label: 'Team' },
  // SOLUSDEV-235: the Store — capabilities are installed, not built in.
  { screen: 'store', icon: <Icons.plus size={17} />, label: 'Store' }
]

/** Bottom rail: account-level screens pinned below the spacer. */
const RAIL_BOTTOM: readonly RailItem[] = [
  { screen: 'billing', icon: <Icons.card size={17} />, label: 'Billing' },
  { screen: 'settings', icon: <Icons.gear size={17} />, label: 'Settings' }
]

/** Whether a rail item is the active screen (Context Model also owns Alert). */
function isRailActive(item: RailItem, name: string): boolean {
  return name === item.screen || (item.screen === 'graph' && name === 'alert')
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
  const renderItem = (item: RailItem): React.JSX.Element => (
    <RailButton
      key={item.screen}
      id={`rail-${item.screen}`}
      icon={item.icon}
      label={item.label}
      active={isRailActive(item, name)}
      onClick={() => go(item.screen)}
    />
  )
  return (
    <div
      style={{
        width: 56,
        borderRight: '1px solid var(--bd)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '12px 0 14px',
        gap: 8,
        flexShrink: 0,
        background: 'var(--sur)'
      }}
    >
      {RAIL_TOP.map(renderItem)}
      <div style={{ flex: 1 }} />
      {RAIL_BOTTOM.map(renderItem)}
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
      className="interactive"
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
