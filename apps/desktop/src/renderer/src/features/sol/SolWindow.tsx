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
import { useEffect, useRef, useState } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { getDesktopSolBridge } from '../../lib/desktopBridge'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore, WORKSPACE_STORAGE_KEY } from '../../store/workspaceStore'
import type { SolState } from '../../../../main/sol-window/solWindow'
import { SolChat } from './SolChat'
import { GuideTasks } from '../guide/GuideTasks'
import { selectSession, startNewChat, useSolChatStore } from './solChatStore'
import { selectConversationId, useSolSessionStore } from './solSessionStore'
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

interface GuideToggle {
  open: boolean
  onToggle: () => void
}

function FooterStart({
  state,
  guide
}: {
  state: SolState | null
  guide: GuideToggle
}): React.JSX.Element {
  return (
    <>
      <Mono size={9.5} color="var(--tx)">
        SOL
      </Mono>
      {state?.screenIntelligence && <span className="sol-window-sees">sees your screen</span>}
      {/* A1: summoned, the pill is the bar alone — the walkthrough picker
          (SOLUSDEV-262) opens on demand instead of holding the panel open. */}
      {state?.actionMode === 'guide' && (
        <button
          type="button"
          className="sol-pill-chip"
          aria-pressed={guide.open}
          onClick={guide.onToggle}
        >
          Guide tasks
        </button>
      )}
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

function Body({
  projectId,
  guide
}: {
  projectId: string | null
  guide: GuideToggle
}): React.JSX.Element {
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
      pillTop={guide.open && state?.actionMode === 'guide' && projectId ? <GuideTasks /> : null}
      pillFooterStart={<FooterStart state={state} guide={guide} />}
      pillFooterEnd={FOOTER_END}
    />
  )
}

/** The latest turn has an approval waiting (an old, forgotten one does not count). */
const latestParked = (s: Parameters<typeof selectSession>[0], projectId: string | null): boolean =>
  (selectSession(s, projectId).items.at(-1)?.confirmations.length ?? 0) > 0

/** Busy = blur must not hide, and a summon must not start over: a turn
 *  streaming, the latest turn's approval waiting, or a plan running. */
function useBusy(projectId: string | null): boolean {
  const streaming = useSolSessionStore((s) => s.streaming)
  const planRunning = useSolWindowStore((s) => s.planRunning)
  const parked = useSolChatStore((s) => latestParked(s, projectId))
  return streaming || parked || planRunning
}

/** The same answer read once, outside React (a summon event). */
const busyNow = (projectId: string): boolean =>
  useSolSessionStore.getState().streaming ||
  useSolWindowStore.getState().planRunning ||
  latestParked(useSolChatStore.getState(), projectId)

/** A1: every summon — the window created, or shown again after a hide — opens
 *  on a NEW chat, unless SOL is busy (then the user comes back to it). The old
 *  conversation stays in the SOL page's history; the pointer is shared with the
 *  page by design, so the page follows. */
function useFreshOnSummon(projectId: string | null, onSummon: () => void): void {
  const latest = useRef(onSummon)
  useEffect(() => {
    latest.current = onSummon
  })
  useEffect(() => {
    if (!projectId) return
    const summoned = (): void => {
      if (document.visibilityState !== 'visible') return
      latest.current()
      if (busyNow(projectId)) return
      if (selectConversationId(useSolSessionStore.getState(), projectId) === null) return
      startNewChat(projectId)
    }
    summoned()
    document.addEventListener('visibilitychange', summoned)
    return () => document.removeEventListener('visibilitychange', summoned)
  }, [projectId])
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
  const [guideOpen, setGuideOpen] = useState(false)
  useFreshOnSummon(projectId, () => setGuideOpen(false))
  // The first getState() is what tells main this renderer is up (markReady)
  // and flushes a region captured before the window finished loading.
  useEffect(() => connectSolBridge(), [])
  useWorkspaceFollow()
  usePillChrome(projectId)
  useReportHeight(ref)
  const lines = statusLines(state)
  return (
    <div className="sol-pill" ref={ref}>
      <Body
        projectId={projectId}
        guide={{ open: guideOpen, onToggle: () => setGuideOpen((open) => !open) }}
      />
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
