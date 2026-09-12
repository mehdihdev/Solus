// SOLUSDEV-252 S3: the SOL window — route #/sol-window, a native-framed,
// resizable, geometry-remembering BrowserWindow main opens on double-tap Ctrl
// or a Ctrl-hold circle (docs/architecture/sol-window.md §2, wireflow §B/§C).
// Header: wordmark · sees-screen dot · pin · close. Under it a
// plain-language status line when something is degraded, the refused-capture
// line, then SolChat (the region card and composer are its). Session and
// project state rehydrate from the shared localStorage; signing in stays a
// main-window flow (the retired OrbWindow's guard, kept).
//
// Perf budget (solWindowPerf.test): no timers or animation frames here — the
// streaming indicator is ONE CSS class (`sol-pulse`).
import { useEffect } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { getDesktopSolBridge } from '../../lib/desktopBridge'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore, WORKSPACE_STORAGE_KEY } from '../../store/workspaceStore'
import type { SolState } from '../../../../main/sol-window/solWindow'
import { SolChat } from './SolChat'
import { useSolSessionStore } from './solSessionStore'
import { connectSolBridge, useSolWindowStore } from './solWindowStore'

const REFUSED_LINE = 'SOL didn’t look — turn on SOL sees your screen in Settings to let it.'

function Centered({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 20,
        fontSize: 12,
        color: 'var(--mut)',
        textAlign: 'center'
      }}
    >
      {children}
    </div>
  )
}

function Header({ state }: { state: SolState | null }): React.JSX.Element {
  const streaming = useSolSessionStore((s) => s.streaming)
  const pinned = state?.alwaysOnTop ?? false
  return (
    <div className="sol-window-header">
      <span className={streaming ? 'sol-window-dot sol-pulse' : 'sol-window-dot'} aria-hidden />
      <Mono size={9.5} color="var(--tx)">
        SOL
      </Mono>
      {state?.screenIntelligence && <span className="sol-window-sees">sees your screen</span>}
      <div style={{ flex: 1 }} />
      <button
        type="button"
        className="sol-window-icon"
        aria-label="Keep on top"
        aria-pressed={pinned}
        onClick={() => void getDesktopSolBridge()?.setAlwaysOnTop(!pinned)}
      >
        Pin
      </button>
      <button
        type="button"
        className="sol-window-icon"
        aria-label="Close"
        onClick={() => window.close()}
      >
        ×
      </button>
    </div>
  )
}

/** Degraded-state lines (wireflow §B), plain text — a settings deep link is
 *  named in the message, never rendered as an anchor. */
function statusLines(state: SolState | null): string[] {
  if (!state) return []
  const lines = [state.hotkeys?.summary ?? '']
  if (state.capture.mode !== 'available') lines.push(state.capture.message)
  return lines.filter((line) => line !== '')
}

function Body({ projectId }: { projectId: string | null }): React.JSX.Element {
  const status = useAuthStore((s) => s.status)
  if (status === 'loading') {
    return (
      <Centered>
        <Spinner size={18} />
      </Centered>
    )
  }
  if (status === 'unauthenticated') {
    return <Centered>Sign in from the main Solus window to use SOL here.</Centered>
  }
  return <SolChat projectId={projectId} layout="panel" />
}

export function SolWindow(): React.JSX.Element {
  const project = useWorkspaceStore((s) => s.project)
  const state = useSolWindowStore((s) => s.state)
  const region = useSolWindowStore((s) => s.region)
  // The first getState() is what tells main this renderer is up (markReady)
  // and flushes a region captured before the window finished loading.
  useEffect(() => connectSolBridge(), [])
  useEffect(() => {
    const syncWorkspace = (event: StorageEvent): void => {
      if (
        event.storageArea === localStorage &&
        (event.key === WORKSPACE_STORAGE_KEY || event.key === null)
      ) {
        void Promise.resolve(useWorkspaceStore.persist.rehydrate()).catch(() => undefined)
      }
    }
    window.addEventListener('storage', syncWorkspace)
    return () => window.removeEventListener('storage', syncWorkspace)
  }, [])
  const lines = statusLines(state)
  return (
    <div className="sol-window">
      <Header state={state} />
      {lines.length > 0 && (
        <div className="sol-window-status">
          {lines.map((line) => (
            <div key={line}>{line}</div>
          ))}
        </div>
      )}
      {state?.lastRegionRefused && region === null && (
        <div className="sol-window-status">{REFUSED_LINE}</div>
      )}
      <Body projectId={project?.id ?? null} />
    </div>
  )
}
