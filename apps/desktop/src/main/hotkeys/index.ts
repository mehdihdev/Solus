// SOLUSDEV-252 S3: the hotkey wiring (docs/architecture/sol-window.md §2-§5,
// wireflow §A-§B). Hook events → Ctrl state machine → summon / cursor sampler →
// circle detector → onRegion. Without the hook, Ctrl+Shift+C opens a 10 s
// circle mode over the same detector. Electron enters only through `deps`.
import type { CapabilityState, PlatformCapabilities } from '../platform/capabilities'
import { analyse, isCircle, regionFor, type Point, type Rect } from '../gesture/circleDetector'
import { createCursorSampler, type Scheduler } from '../gesture/cursorSampler'
import { createCtrlStateMachine, distance, type CtrlOutput } from './ctrlStateMachine'
import {
  registerGlobalHotkeys,
  summonShortcutLabel,
  type GlobalShortcutApi,
  type ShortcutStatus
} from './globalHotkeys'
import { loadKeyHook, type KeyHookLoad } from './keyHook'

export type { Rect, Point }
export type { KeyHook, KeyHookLoad } from './keyHook'

export const CIRCLE_MODE_MS = 10_000
export const CIRCLE_MODE_EVAL_AT_MS = 8_000
export const CIRCLE_MODE_PAUSE_MS = 300

export interface DisplayInfo {
  id: number
  bounds: Rect
  scaleFactor: number
}

export interface HotkeyDeps {
  capabilities: PlatformCapabilities
  globalShortcut: GlobalShortcutApi
  getCursor(): Point
  displayFor(point: Point): DisplayInfo
  now(): number
  scheduler: Scheduler
  /** Default: the real `uiohook-napi` loader. Tests inject a fake. */
  loadHook?: (basics: PlatformCapabilities) => KeyHookLoad
  /** darwin only: `systemPreferences.isTrustedAccessibilityClient(false)`. */
  isTrustedAccessibilityClient?: () => boolean
  onSummon(): void
  onToggleMode(): void
  onRegion(region: Rect, display: DisplayInfo): void
  onStatus(status: HotkeyStatus): void
  /** Diagnostic sink (coordinates and evaluations only, never pixels). */
  debug?: (line: string) => void
}

export interface HotkeyStatus {
  hook: CapabilityState
  shortcuts: ShortcutStatus
  mode: 'hook' | 'fallback'
  circleModeActive: boolean
  /** The one-line status for the window status line and the tray tooltip (§B). */
  summary: string
}

export interface HotkeysHandle {
  status(): HotkeyStatus
  enterCircleMode(): void
  stop(): void
}

export function summaryFor(
  s: Omit<HotkeyStatus, 'summary'>,
  extra: string[],
  platform = 'linux'
): string {
  const line = s.circleModeActive
    ? 'Circle mode — draw a loop'
    : s.mode === 'hook'
      ? 'Hold Ctrl and circle to focus SOL on something'
      : 'Circle mode: press Ctrl+Shift+C, then draw a loop'
  const summon = s.shortcuts.spawnFallback
    ? `${summonShortcutLabel(platform)} — open SOL`
    : 'Open SOL window from the SOL page'
  return [s.circleModeActive ? line : `${summon} · ${line}`, ...extra].join(' · ')
}

interface CircleMode {
  startedAt: number
  path: Point[]
  lastMoveAt: number
  evaluatedLate: boolean
}

/** Append one cursor sample to the circle-mode stroke and say whether it is
 *  time to evaluate it: the cursor paused, or the 8 s check is due. */
function sampleCircle(
  c: CircleMode,
  t: number,
  at: Point
): { next: CircleMode; paused: boolean; late: boolean } {
  const prev = c.path[c.path.length - 1]
  const moved = !prev || distance(prev, at) >= 1
  const next = { ...c, path: [...c.path, at], lastMoveAt: moved ? t : c.lastMoveAt }
  const paused = !moved && next.path.length > 1 && t - next.lastMoveAt >= CIRCLE_MODE_PAUSE_MS
  const late = t - c.startedAt >= CIRCLE_MODE_EVAL_AT_MS && !c.evaluatedLate
  return { next, paused, late }
}

export function startHotkeys(deps: HotkeyDeps): HotkeysHandle {
  const { capabilities } = deps
  const load =
    deps.loadHook ??
    ((b) => loadKeyHook(b, { isTrustedAccessibilityClient: deps.isTrustedAccessibilityClient }))
  const { hook, state: hookState } = load(capabilities)
  const machine = createCtrlStateMachine()

  const emitRegion = (path: Point[]): boolean => emitCircleRegion(deps, path)

  const sampler = createCursorSampler({
    getCursor: () => deps.getCursor(),
    now: () => deps.now(),
    scheduler: deps.scheduler,
    onSample: (t, at) =>
      circleMode.active() ? circleMode.sample(t, at) : act(machine.feed({ type: 'cursor', t, at }))
  })

  const act = (outputs: CtrlOutput[]): void => {
    for (const o of outputs) {
      if (o.type === 'doubleTap') deps.onSummon()
      else if (o.type === 'gestureEnd') emitRegion(o.path)
    }
  }

  const circleMode = createCircleMode(deps, machine, sampler, emitRegion, () => publish())
  const enterCircleMode = circleMode.enter

  const shortcuts = registerGlobalHotkeys(deps.globalShortcut, {
    available: capabilities.globalShortcuts.status !== 'unavailable',
    hookAvailable: hook !== null,
    platform: capabilities.platform,
    onToggleMode: () => deps.onToggleMode(),
    onSummon: () => deps.onSummon(),
    onCircleMode: enterCircleMode
  })

  hook?.onCtrlDown(() => {
    act(machine.feed({ type: 'ctrlDown', t: deps.now(), at: deps.getCursor() }))
    sampler.arm() // ponytail: 60 Hz from ctrlDown (travel decides tap vs gesture), off at ctrlUp
  })
  hook?.onCtrlUp(() => {
    act(machine.feed({ type: 'ctrlUp', t: deps.now() }))
    if (!circleMode.active()) sampler.disarm()
  })
  hook?.onOtherKeyDown(() => {
    act(machine.feed({ type: 'otherKeyDown', t: deps.now() }))
    if (!circleMode.active()) sampler.disarm()
  })

  const status = (): HotkeyStatus => {
    const base = {
      hook: hookState,
      shortcuts: shortcuts.shortcuts,
      mode: hook ? ('hook' as const) : ('fallback' as const),
      circleModeActive: circleMode.active()
    }
    const extra = [
      ...(capabilities.globalShortcuts.status !== 'available'
        ? [capabilities.globalShortcuts.message]
        : []),
      ...shortcuts.messages
    ]
    return { ...base, summary: summaryFor(base, extra, capabilities.platform) }
  }
  const publish = (): void => deps.onStatus(status())
  publish()

  return {
    status,
    enterCircleMode,
    stop() {
      circleMode.clear()
      sampler.disarm()
      shortcuts.stop()
      hook?.stop()
    }
  }
}

/** Own the bounded fallback stroke independently of native key events. */
function createCircleMode(
  deps: HotkeyDeps,
  machine: ReturnType<typeof createCtrlStateMachine>,
  sampler: ReturnType<typeof createCursorSampler>,
  emitRegion: (path: Point[]) => boolean,
  publish: () => void
): { active(): boolean; enter(): void; sample(t: number, at: Point): void; clear(): void } {
  let circle: CircleMode | null = null
  const exitCircleMode = (): void => {
    circle = null
    if (machine.phase() === 'idle') sampler.disarm()
    publish()
  }

  // SOLUS_DEBUG_GESTURE=1: cursor samples and evaluations (coordinates only) —
  // the QA knob for "the gesture does nothing on my machine".
  const trace = (t: number, c: CircleMode, at: Point, paused: boolean, late: boolean): void => {
    if (!deps.debug || !(paused || late || c.path.length % 30 === 1)) return
    const verdict = paused || late ? ` analysis=${JSON.stringify(analyse(c.path))}` : ''
    deps.debug(
      `circle t+${t - c.startedAt}ms n=${c.path.length} at=${at.x},${at.y} paused=${paused} late=${late}${verdict}`
    )
  }

  const onCircleSample = (t: number, at: Point): void => {
    if (!circle) return
    if (t - circle.startedAt >= CIRCLE_MODE_MS) return exitCircleMode()
    const { next, paused, late } = sampleCircle(circle, t, at)
    circle = next
    trace(t, next, at, paused, late)
    if (!paused && !late) return
    if (emitRegion(next.path)) return exitCircleMode()
    // A failed evaluation KEEPS the stroke: a hand that hesitates mid-loop (live
    // gate, 2026-09-07: a 300 ms stall split one circle into two half-strokes)
    // must not lose what it drew. The stroke is bounded by the 10 s window.
    if (late) circle = { ...next, evaluatedLate: true }
  }

  const enterCircleMode = (): void => {
    circle = { startedAt: deps.now(), path: [], lastMoveAt: deps.now(), evaluatedLate: false }
    sampler.arm()
    publish()
  }

  return {
    active: () => circle !== null,
    enter: enterCircleMode,
    sample: onCircleSample,
    clear: () => {
      circle = null
    }
  }
}

function emitCircleRegion(deps: HotkeyDeps, path: Point[]): boolean {
  const a = analyse(path)
  if (!isCircle(a)) return false
  const display = deps.displayFor(a.centroid)
  deps.onRegion(regionFor(a, display), display)
  return true
}
