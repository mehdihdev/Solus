// Workspace shell — the app home, ported from the authed App() in
// TestDesign/app/shell-main.jsx: icon rail, topbar (project / screen / search /
// bell), notifications popover, magic-moment toast, guided tour, mini orb, and
// the five screens plus the alert detail view.
import { useEffect, useState } from 'react'
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
import { GuideTour, type TourState } from '../sol/GuideTour'
import { TeamScreen } from '../team/TeamScreen'
import { SettingsScreen } from '../team/SettingsScreen'
import { TopBar, NotifPopover, ToastView } from './ShellChrome'
import {
  ALERTS,
  FALLBACK_PROJECT_NAME,
  SCREEN_TITLES,
  SOL_SCRIPTS,
  type Alert
} from './workspaceData.constants'
import { alertsWithState, openAlertCount, useShellStore, type MainScreen } from './shellStore'

type Route = { name: MainScreen } | { name: 'alert'; alertId: string }

const TOAST_DELAY_MS = 5000
const ASK_DELAY_MS = 350
const ANSWER_DELAY_MS = 1700

/** Queue a scripted SOL exchange unless that question was already asked. */
function askSolScript(key: string): void {
  const script = SOL_SCRIPTS[key]
  if (!script) return
  const asked = useShellStore.getState().chat.some((m) => m.role === 'user' && m.text === script.q)
  if (asked) return
  setTimeout(() => {
    useShellStore.getState().appendChat({ role: 'user', text: script.q })
    setTimeout(
      () => useShellStore.getState().appendChat({ role: 'sol', scriptKey: key }),
      ANSWER_DELAY_MS
    )
  }, ASK_DELAY_MS)
}

function buildTourSteps(a1Resolved: boolean): TourState['steps'] {
  return [
    {
      target: '#rail-bell',
      text: 'Alerts live here. The red badge means SOL found something that crosses domains. Let me open it for you.',
      action: 'click'
    },
    {
      target: '#notif-a1',
      text: "This is the catch — Priya's U4 swap on the PCB silently breaks your firmware. Click through to see the full trace.",
      action: 'click'
    },
    a1Resolved
      ? {
          target: '#rail-bench',
          text: "This one's already resolved — the patch is merged. Next time something breaks, you'll see it live on the Bench here.",
          action: null
        }
      : {
          target: '#btn-apply-fix',
          text: 'SOL prepared the patch already — review the diff above, then apply it from here. It opens a PR, so nothing lands unreviewed.',
          action: null
        }
  ]
}

/** Magic-moment toast: fires once, shortly after first landing on the graph. */
function useMagicMomentToast(screenName: string): void {
  const toastShown = useShellStore((s) => s.toastShown)
  useEffect(() => {
    if (toastShown || screenName !== 'graph') return
    const t = setTimeout(() => {
      const shell = useShellStore.getState()
      shell.setToast({
        title: 'SOL caught a cross-domain break',
        body: 'Priya swapped U4 (DRV8833 → DRV8316C) 2h ago — it breaks the pin map in 3 firmware files.',
        action: 'View alert',
        alertId: 'a1'
      })
      shell.markToastShown()
    }, TOAST_DELAY_MS)
    return () => clearTimeout(t)
  }, [toastShown, screenName])
}

export function WorkspaceShell(): React.JSX.Element {
  const navigate = useNavigate()
  const [route, setRoute] = useState<Route>({ name: 'graph' })
  const [notifOpen, setNotifOpen] = useState(false)
  const [tour, setTour] = useState<TourState | null>(null)
  const resolved = useShellStore((s) => s.resolved)
  const anomaly = useShellStore((s) => s.anomaly)
  const email = useAuthStore((s) => s.user?.email)
  const signOut = useAuthStore((s) => s.signOut)
  const project = useWorkspaceStore((s) => s.project)

  const alerts = alertsWithState(ALERTS, resolved)
  const name = route.name
  useMagicMomentToast(name)

  const go = (screen: MainScreen): void => {
    useShellStore.getState().setLastMain(screen)
    setRoute({ name: screen })
    setNotifOpen(false)
  }
  const openAlert = (alertId: string): void => {
    setRoute({ name: 'alert', alertId })
    setNotifOpen(false)
  }
  const askSol = (key: string): void => {
    go('sol')
    askSolScript(key)
  }
  const startTour = (): void => {
    setNotifOpen(false)
    setTour({
      steps: buildTourSteps(!!useShellStore.getState().resolved.a1),
      idx: 0,
      advance: () => setTour((t) => (t ? { ...t, idx: t.idx + 1 } : t))
    })
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
      <Rail name={name} anomaly={anomaly === 'active'} go={go} email={email} />
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
          projectName={project?.name ?? FALLBACK_PROJECT_NAME}
          screenTitle={SCREEN_TITLES[name] ?? ''}
          openCount={openAlertCount(alerts)}
          onBell={() => setNotifOpen((o) => !o)}
          onSignOut={() => void onSignOut()}
        />
        {notifOpen && (
          <NotifPopover alerts={alerts} onOpen={openAlert} onClose={() => setNotifOpen(false)} />
        )}
        <div
          data-screen-label={SCREEN_TITLES[name]}
          style={{ flex: 1, display: 'flex', minHeight: 0, position: 'relative' }}
        >
          <ScreenView
            route={route}
            alerts={alerts}
            openAlert={openAlert}
            askSol={askSol}
            startTour={startTour}
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
      <MiniOrb hidden={name === 'sol' || !!tour} onClick={() => go('sol')} />
      {tour && <GuideTour tour={tour} onEnd={() => setTour(null)} />}
    </div>
  )
}

function ScreenView({
  route,
  alerts,
  openAlert,
  askSol,
  startTour,
  goBack
}: {
  route: Route
  alerts: readonly Alert[]
  openAlert: (id: string) => void
  askSol: (key: string) => void
  startTour: () => void
  goBack: () => void
}): React.JSX.Element | null {
  switch (route.name) {
    case 'graph':
      return <GraphScreen onOpenAlert={openAlert} onAskSol={askSol} />
    case 'bench':
      return <BenchScreen onAskSol={askSol} />
    case 'sol':
      return <SolScreen onOpenAlert={openAlert} onStartTour={startTour} />
    case 'team':
      return <TeamScreen onOpenAlert={openAlert} />
    case 'settings':
      return <SettingsScreen />
    case 'alert': {
      const alert = alerts.find((a) => a.id === route.alertId)
      if (!alert) return null
      return <AlertScreen key={alert.id} alertId={alert.id} onBack={goBack} onAskSol={askSol} />
    }
  }
}

function Rail({
  name,
  anomaly,
  go,
  email
}: {
  name: string
  anomaly: boolean
  go: (screen: MainScreen) => void
  email?: string
}): React.JSX.Element {
  const railName = email ? email.split('@')[0].replace(/[._-]/g, ' ') : 'Maya Krishnan'
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
      <div onClick={() => go('graph')} style={{ marginBottom: 12, cursor: 'pointer' }}>
        <SolOrb size={24} />
      </div>
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
        badge={anomaly}
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
        id="rail-settings"
        icon={<Icons.gear size={17} />}
        label="Settings"
        active={name === 'settings'}
        onClick={() => go('settings')}
      />
      <div style={{ marginTop: 4 }}>
        <Avatar name={railName} size={26} />
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
