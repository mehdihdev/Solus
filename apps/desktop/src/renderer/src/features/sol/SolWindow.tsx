// SOLUSDEV-252 S3: the SOL window — route #/sol-window, opened on double-tap
// Ctrl or a Ctrl-hold circle (docs/architecture/sol-window.md §2, wireflow
// §B/§C). Session and project state rehydrate from the shared localStorage;
// signing in stays a main-window flow (the retired OrbWindow's guard, kept).
//
// SOLUSDEV-319: the Ember Pill. A transparent, frameless window that main sizes
// from the height measured here: the bar (orb · input · Guide|Build · send) and
// footer sit at the bottom, the panel (Guide tasks, the thread, the region
// card) grows above them. Esc and the hide button hide it through main; it
// reports busy (streaming, approval parked, plan running) so blur leaves it up.
//
// Perf budget (solWindowPerf.test): no timers or animation frames here — the
// streaming indicator is ONE CSS class (`sol-pulse`); sizing is a ResizeObserver.
import { useEffect, useRef } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { getDesktopSolBridge } from '../../lib/desktopBridge'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore, WORKSPACE_STORAGE_KEY } from '../../store/workspaceStore'
import type { SolState } from '../../../../main/sol-window/solWindow'
import { SolChat } from './SolChat'
import { GuideTasks } from '../guide/GuideTasks'
import { selectSession, useSolChatStore } from './solChatStore'
import { useSolSessionStore } from './solSessionStore'
import { connectSolBridge, useSolWindowStore } from './solWindowStore'

const REFUSED_LINE = 'SOL didn’t look — turn on SOL sees your screen in Settings to let it.'

const hidePill = (): void => void getDesktopSolBridge()?.hide()

/** Degraded-state lines (wireflow §B), plain text — a settings deep link is
 *  named in the message, never rendered as an anchor. */
function statusLines(state: SolState | null): string[] {
  if (!state) return []
  const lines = [state.hotkeys?.summary ?? '']
  if (state.capture.mode !== 'available') lines.push(state.capture.message)
  return lines.filter((line) => line !== '')
}

function FooterStart({ state }: { state: SolState | null }): React.JSX.Element {
  return (
    <>
      <Mono size={9.5} color="var(--tx)">
        SOL
      </Mono>
      {state?.screenIntelligence && <span className="sol-window-sees">sees your screen</span>}
    </>
  )
}

const FOOTER_END = (
  <button type="button" className="sol-pill-hide" aria-label="Hide SOL" onClick={hidePill}>
    ×
  </button>
)

function Notice({ children }: { children: React.ReactNode }): React.JSX.Element {
  return <div className="sol-pill-bar sol-pill-notice">{children}</div>
}

function Body({ projectId }: { projectId: string | null }): React.JSX.Element {
  const status = useAuthStore((s) => s.status)
  const state = useSolWindowStore((s) => s.state)
  if (status === 'loading') {
    return (
      <Notice>
        <Spinner size={18} />
      </Notice>
    )
  }
  if (status === 'unauthenticated') {
    return <Notice>Sign in from the main Solus window to use SOL here.</Notice>
  }
  return (
    <SolChat
      projectId={projectId}
      layout="pill"
      pillTop={state?.actionMode === 'guide' && projectId ? <GuideTasks /> : null}
      pillFooterStart={<FooterStart state={state} />}
      pillFooterEnd={FOOTER_END}
    />
  )
}

/** Busy = blur must not hide: a turn streaming, the LATEST turn's approval
 *  waiting (an old, forgotten one must not pin the pill over every app), or a
 *  plan running. */
function useBusy(projectId: string | null): boolean {
  const streaming = useSolSessionStore((s) => s.streaming)
  const planRunning = useSolWindowStore((s) => s.planRunning)
  const parked = useSolChatStore(
    (s) => (selectSession(s, projectId).items.at(-1)?.confirmations.length ?? 0) > 0
  )
  return streaming || parked || planRunning
}

/** Main sizes the window from this; the bottom edge stays put (grows upward). */
function useReportHeight(ref: React.RefObject<HTMLDivElement | null>): void {
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => {
      void getDesktopSolBridge()?.resize(Math.ceil(el.getBoundingClientRect().height))
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])
}

function usePillChrome(projectId: string | null): void {
  const busy = useBusy(projectId)
  useEffect(() => {
    void getDesktopSolBridge()?.setBusy(busy)
  }, [busy])
  useEffect(() => {
    // An Escape a control already used (the mention list) is not ours.
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape' && !event.defaultPrevented) hidePill()
    }
    window.addEventListener('keydown', onKey)
    document.documentElement.classList.add('sol-pill-host')
    return () => {
      window.removeEventListener('keydown', onKey)
      document.documentElement.classList.remove('sol-pill-host')
    }
  }, [])
}

function useWorkspaceFollow(): void {
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
}

export function SolWindow(): React.JSX.Element {
  const project = useWorkspaceStore((s) => s.project)
  const state = useSolWindowStore((s) => s.state)
  const region = useSolWindowStore((s) => s.region)
  const ref = useRef<HTMLDivElement>(null)
  const projectId = project?.id ?? null
  // The first getState() is what tells main this renderer is up (markReady)
  // and flushes a region captured before the window finished loading.
  useEffect(() => connectSolBridge(), [])
  useWorkspaceFollow()
  usePillChrome(projectId)
  useReportHeight(ref)
  const lines = statusLines(state)
  return (
    <div className="sol-pill" ref={ref}>
      <Body projectId={projectId} />
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
    </div>
  )
}
