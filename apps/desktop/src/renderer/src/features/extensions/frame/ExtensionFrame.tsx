// SOLUSDEV-235 / EXT-13 — the ONLY element extension code ever renders in:
// `<iframe sandbox="allow-scripts">` over `solus-ext://` (architecture §2, §3).
// No `allow-same-origin` (opaque origin), no preload, no srcdoc, no permissions
// (`allow=""`), no referrer. The bridge hook owns the messages; this component
// owns the element, the loading → ready → error state machine (§6.2) and the
// fade-in. Nothing from the frame is ever placed into host DOM.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { WidgetRenderState } from '@solus/shared-types'
import type { BridgeDeps } from '../host/bridgeDeps'
import { useExtensionBridge } from '../host/useExtensionBridge'
import { extEntryUrl } from './extUrl'
import { FrameCard, FrameSkeleton } from './FrameStates'
import type {
  BundleView,
  InstalledBundleDeps,
  InstalledBundleState,
  ReadyBundle
} from './installedBundle'
import { useInstalledBundle, type InstalledBundle } from './useInstalledBundle'

/** §6.2: `ui.ready` must arrive within this window or the frame is `error`. */
export const HANDSHAKE_TIMEOUT_MS = 10_000
/** The sandbox token set. Exactly this — tests pin it. */
export const FRAME_SANDBOX = 'allow-scripts'

export interface ExtensionFrameProps {
  readonly projectId: string
  readonly slug: string
  readonly view: BundleView
  /** CTR-01 `WidgetRenderState` for the canvas / screen chrome. */
  readonly onStateChange?: (state: WidgetRenderState) => void
  /** A resolution the parent already holds (page/window screens share one with their header). */
  readonly bundle?: InstalledBundle
  /** Extra buttons on the error / blocked / disabled cards (e.g. "Open in Store"). */
  readonly actions?: ReactNode
  readonly bundleDeps?: InstalledBundleDeps
  readonly bridgeDeps?: BridgeDeps
  readonly handshakeTimeoutMs?: number
}

type Handshake = 'pending' | 'ready' | 'timeout'

interface MountedFrameProps {
  readonly bundle: ReadyBundle
  readonly src: string
  readonly bridgeDeps?: BridgeDeps
  readonly timeoutMs: number
  readonly onHandshake: (state: Handshake) => void
}

/** The iframe + its bridge host. Remounted (by key) on every retry so the host,
 *  the load listener and the timer all start over together. */
function MountedFrame({
  bundle,
  src,
  bridgeDeps,
  timeoutMs,
  onHandshake
}: MountedFrameProps): React.JSX.Element {
  const frameRef = useRef<HTMLIFrameElement | null>(null)
  const { ready } = useExtensionBridge({
    frameRef,
    policy: bundle.policy,
    settings: bundle.settings,
    deps: bridgeDeps
  })
  useEffect(() => {
    if (ready) {
      onHandshake('ready')
      return
    }
    const timer = setTimeout(() => onHandshake('timeout'), timeoutMs)
    return () => clearTimeout(timer)
  }, [ready, timeoutMs, onHandshake])
  return (
    <iframe
      ref={frameRef}
      sandbox={FRAME_SANDBOX}
      src={src}
      title={`${bundle.name} (${bundle.policy.mode})`}
      referrerPolicy="no-referrer"
      allow=""
      data-testid="extension-frame"
      className={ready ? 'screen-in' : undefined}
      style={{
        flex: 1,
        width: '100%',
        minHeight: 0,
        border: 0,
        background: 'transparent',
        visibility: ready ? 'visible' : 'hidden'
      }}
    />
  )
}

function toRenderState(state: InstalledBundleState, handshake: Handshake): WidgetRenderState {
  if (state.status === 'ready')
    return handshake === 'ready' ? 'ready' : handshake === 'timeout' ? 'error' : 'loading'
  if (state.status === 'loading' || state.status === 'caching') return 'loading'
  return 'error'
}

interface NotReadyProps {
  readonly slug: string
  readonly state: Exclude<InstalledBundleState, ReadyBundle>
  readonly onRetry: () => void
  readonly actions?: ReactNode
}

/** Every non-ready bundle state → skeleton or card (wireflow §2 copy). */
function NotReady({ slug, state, onRetry, actions }: NotReadyProps): React.JSX.Element {
  switch (state.status) {
    case 'loading':
      return <FrameSkeleton text={`Loading ${slug}…`} />
    case 'caching':
      return <FrameSkeleton text={`Downloading ${state.name}…`} />
    case 'not_installed':
      return (
        <FrameCard
          tone="error"
          title={`${slug} isn't installed in this project.`}
          onRetry={onRetry}
          actions={actions}
        />
      )
    case 'blocked':
      return <FrameCard tone="blocked" title="Blocked by your team." actions={actions} />
    case 'disabled':
      return (
        <FrameCard
          tone="disabled"
          title={`${state.name} is disabled in this project.`}
          actions={actions}
        />
      )
    default:
      return state.step === 'no_desktop' ? (
        <FrameCard tone="error" title={state.message} actions={actions} />
      ) : (
        <FrameCard
          tone="error"
          title={`${slug} didn't start.`}
          detail={state.message}
          onRetry={onRetry}
          actions={actions}
        />
      )
  }
}

interface FrameBodyProps extends Omit<ExtensionFrameProps, 'bundle' | 'bundleDeps'> {
  readonly bundle: InstalledBundle
}

function FrameBody(props: FrameBodyProps): React.JSX.Element {
  const { slug, view, onStateChange, actions, bridgeDeps, bundle } = props
  const { state } = bundle
  const timeoutMs = props.handshakeTimeoutMs ?? HANDSHAKE_TIMEOUT_MS
  const [attempt, setAttempt] = useState(0)
  const [handshake, setHandshake] = useState<Handshake>('pending')

  const renderState = toRenderState(state, handshake)
  const reported = useRef<WidgetRenderState | null>(null)
  useEffect(() => {
    if (reported.current === renderState) return
    reported.current = renderState
    onStateChange?.(renderState)
  }, [renderState, onStateChange])

  const remount = (): void => {
    setHandshake('pending')
    setAttempt((n) => n + 1)
  }

  if (state.status !== 'ready') {
    return <NotReady slug={slug} state={state} onRetry={bundle.retry} actions={actions} />
  }
  const src = extEntryUrl(state.policy.extensionId, state.version, state.entry, {
    nonce: state.policy.mode === 'dev' ? attempt : undefined
  })
  if (src === null) {
    return (
      <FrameCard
        tone="error"
        title={`${state.name} didn't start.`}
        detail={`Its ${view} entry is not a valid bundle path.`}
        actions={actions}
      />
    )
  }
  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        position: 'relative'
      }}
    >
      <MountedFrame
        key={attempt}
        bundle={state}
        src={src}
        bridgeDeps={bridgeDeps}
        timeoutMs={timeoutMs}
        onHandshake={setHandshake}
      />
      {handshake !== 'ready' && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex' }}>
          {handshake === 'pending' ? (
            <FrameSkeleton text={`Loading ${state.name}…`} />
          ) : (
            <FrameCard
              tone="error"
              title={`${state.name} didn't start.`}
              detail={`It did not respond in ${Math.round(timeoutMs / 1000)} s.`}
              requestPath={state.policy.mode === 'dev' ? src : undefined}
              onRetry={remount}
              retryLabel="Reload"
              actions={actions}
            />
          )}
        </div>
      )}
    </div>
  )
}

/** Uncontrolled: resolves the bundle itself (the widget canvas case). */
function SelfResolvingFrame(props: Omit<ExtensionFrameProps, 'bundle'>): React.JSX.Element {
  const bundle = useInstalledBundle(props.projectId, props.slug, props.view, props.bundleDeps)
  return <FrameBody {...props} bundle={bundle} />
}

export function ExtensionFrame(props: ExtensionFrameProps): React.JSX.Element {
  // A parent that already resolved the bundle (page / window screens share it
  // with their header) hands it down; the frame must not resolve it a second time.
  if (props.bundle !== undefined) return <FrameBody {...props} bundle={props.bundle} />
  return <SelfResolvingFrame {...props} />
}
