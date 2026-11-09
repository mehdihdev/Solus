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
// Motion (summon in, exit out, the panel's height, rows arriving) is CSS only,
// keyed off `data-phase` and main's `sol:pill` cues; main owns the 5 s resume
// rule and waits a bounded time for the exit before hiding the window.
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
import { connectSolBridge, useFrontAppSnapshot, useSolWindowStore } from './solWindowStore'
import { measurePill } from './pillMeasure'
import { pillHeightCap } from './solPill.constants'

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

/** Start over unless SOL is busy or there is nothing to forget. */
function startFresh(projectId: string): void {
  if (busyNow(projectId)) return
  if (selectConversationId(useSolSessionStore.getState(), projectId) === null) return
  startNewChat(projectId)
}

type PillPhase = 'in' | 'leaving'

/** A1 + SOLUSDEV-319: the window created (mount) opens on a NEW chat, and so
 *  does a re-summon main marks `resume: false` (hidden more than 5 s) — unless
 *  SOL is busy, then the user comes back to it. A `resume: true` summon keeps
 *  everything (messages, draft, scroll). The old conversation stays in the SOL
 *  page's history; the pointer is shared with the page by design. Returns the
 *  motion phase main last cued. */
function useSummons(projectId: string | null, onFresh: () => void): PillPhase {
  const [phase, setPhase] = useState<PillPhase>('in')
  const latest = useRef(onFresh)
  useEffect(() => {
    latest.current = onFresh
  })
  useEffect(() => {
    if (!projectId) return
    latest.current()
    startFresh(projectId)
  }, [projectId])
  useEffect(() => {
    const off = getDesktopSolBridge()?.onPill?.((event) => {
      if (event.kind === 'leaving') return setPhase('leaving')
      setPhase('in')
      if (event.resume) return
      latest.current()
      if (projectId) startFresh(projectId)
    })
    return off
  }, [projectId])
  return phase
}

/** Main sizes the window from this; the bottom edge stays put (grows upward).
 *  The panel's room is whatever the cap leaves after the bar and footer, so
 *  the thread scrolls inside rather than push the composer off the window. */
function useReportHeight(ref: React.RefObject<HTMLDivElement | null>, cap: number): void {
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    let sent = -1
    let room = -1
    const measure = (): void => {
      const { report, chrome } = measurePill(el)
      // Only on change: writing it re-lays-out the observed subtree.
      const nextRoom = Math.max(0, Math.floor(cap - chrome))
      if (nextRoom !== room) {
        room = nextRoom
        el.style.setProperty('--sol-pill-panel-room', `${nextRoom}px`)
      }
      if (report === sent) return
      sent = report
      void getDesktopSolBridge()?.resize(report)
    }
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    // A fresh summon resets the window to the collapsed height; if the content
    // is the same height as before, no resize fires, so report it again.
    const off = getDesktopSolBridge()?.onPill?.((event) => {
      if (event.kind !== 'summoned' || event.resume) return
      sent = -1
      measure()
    })
    return () => {
      observer.disconnect()
      off?.()
    }
  }, [ref, cap])
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
  const phase = useSummons(projectId, () => setGuideOpen(false))
  const [cap] = useState(() => pillHeightCap(window.screen.availHeight))
  // The first getState() is what tells main this renderer is up (markReady)
  // and flushes a region captured before the window finished loading.
  useEffect(() => connectSolBridge(), [])
  // SOLUSDEV-319 slice 4: the pill's turns carry the app it was summoned over.
  useFrontAppSnapshot()
  useWorkspaceFollow()
  usePillChrome(projectId)
  useReportHeight(ref, cap)
  const lines = statusLines(state)
  return (
    <div
      className="sol-pill"
      ref={ref}
      data-phase={phase}
      style={{ '--sol-pill-max-h': `${cap}px` } as React.CSSProperties}
    >
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
