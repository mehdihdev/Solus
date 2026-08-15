// SOLX-02: the persistent SOL orb (consolidates SOL-04/05/06). Keeps the
// MiniOrb export + props so WorkspaceShell's mount is untouched: `hidden`
// still hides it on the SOL screen, and `onClick` is now the "Open SOL
// screen" hand-off in the panel header.
//
// Perf budget (SOL-05, defined here): idle costs ~0 — CSS-only rendering with
// no animation-frame or timer scheduling anywhere in this module (orbPerf
// ratchets that structurally), pulse ≤ 1 CSS animation driven by store
// streaming state, reduced-motion switches it off.
import { useRef, useState } from 'react'
import { SolOrb } from '../../components/ui/SolOrb'
import { Mono } from '../../components/ui/Mono'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { OrbChat } from './OrbChat'
import { cornerFor, selectOrbPulse, useOrbStore, type OrbCorner } from './orbStore'
import { getSolWindowBridge } from './solWindowBridge'

const EDGE = 18
const ORB_SIZE = 44
const PANEL_OFFSET = EDGE + ORB_SIZE + 10
const DRAG_THRESHOLD_PX = 5

const CORNER_POS: Record<OrbCorner, React.CSSProperties> = {
  tl: { left: EDGE, top: EDGE },
  tr: { right: EDGE, top: EDGE },
  bl: { left: EDGE, bottom: EDGE },
  br: { right: EDGE, bottom: EDGE }
}

const PANEL_POS: Record<OrbCorner, React.CSSProperties> = {
  tl: { left: EDGE, top: PANEL_OFFSET },
  tr: { right: EDGE, top: PANEL_OFFSET },
  bl: { left: EDGE, bottom: PANEL_OFFSET },
  br: { right: EDGE, bottom: PANEL_OFFSET }
}

const BARE_BUTTON: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  padding: 0,
  cursor: 'pointer',
  display: 'block'
}

const HEADER_BUTTON: React.CSSProperties = {
  background: 'transparent',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  color: 'var(--mut)',
  fontSize: 10.5,
  padding: '3px 8px',
  cursor: 'pointer'
}

function PanelHeader({
  onOpenScreen,
  onDetach,
  onClose
}: {
  onOpenScreen: () => void
  onDetach: (() => void) | null
  onClose: () => void
}): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 10px',
        borderBottom: '1px solid var(--bd)'
      }}
    >
      <SolOrb size={16} />
      <Mono size={9.5} color="var(--tx)">
        SOL
      </Mono>
      <div style={{ flex: 1 }} />
      <button type="button" style={HEADER_BUTTON} onClick={onOpenScreen}>
        Open SOL screen
      </button>
      {onDetach && (
        <button type="button" style={HEADER_BUTTON} onClick={onDetach} aria-label="Detach SOL">
          Detach
        </button>
      )}
      <button type="button" style={HEADER_BUTTON} onClick={onClose} aria-label="Close SOL panel">
        ×
      </button>
    </div>
  )
}

function DetachedOrb({ corner }: { corner: OrbCorner }): React.JSX.Element {
  const reattach = async (): Promise<void> => {
    await getSolWindowBridge()?.attach()
    useOrbStore.getState().setDetached(false)
  }
  return (
    <div style={{ position: 'fixed', ...CORNER_POS[corner], zIndex: 60, opacity: 0.4 }}>
      <button
        type="button"
        aria-label="SOL is detached — click to re-attach"
        title="SOL is detached — click to re-attach"
        onClick={() => void reattach()}
        style={BARE_BUTTON}
      >
        <SolOrb size={ORB_SIZE} />
      </button>
    </div>
  )
}

interface MiniOrbProps {
  hidden: boolean
  onClick: () => void
}

export function MiniOrb({ hidden, onClick }: MiniOrbProps): React.JSX.Element | null {
  const corner = useOrbStore((s) => s.corner)
  const expanded = useOrbStore((s) => s.expanded)
  const detached = useOrbStore((s) => s.detached)
  const pulse = useOrbStore(selectOrbPulse)
  const project = useWorkspaceStore((s) => s.project)
  const [dragPos, setDragPos] = useState<{ x: number; y: number } | null>(null)
  const startRef = useRef<{ x: number; y: number } | null>(null)
  const suppressClickRef = useRef(false)

  if (hidden) return null
  if (detached) return <DetachedOrb corner={corner} />

  const bridge = getSolWindowBridge()

  const onPointerDown = (e: React.PointerEvent<HTMLButtonElement>): void => {
    startRef.current = { x: e.clientX, y: e.clientY }
    // Without capture, a drag that leaves this 44px button stops delivering
    // move/up events to it — the orb freezes mid-flight and never snaps.
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent<HTMLButtonElement>): void => {
    const start = startRef.current
    if (!start) return
    const moved = Math.hypot(e.clientX - start.x, e.clientY - start.y)
    if (dragPos !== null || moved > DRAG_THRESHOLD_PX) {
      setDragPos({ x: e.clientX, y: e.clientY })
    }
  }
  const onPointerUp = (e: React.PointerEvent<HTMLButtonElement>): void => {
    startRef.current = null
    e.currentTarget.releasePointerCapture?.(e.pointerId)
    if (dragPos === null) return
    useOrbStore
      .getState()
      .setCorner(cornerFor(e.clientX, e.clientY, window.innerWidth, window.innerHeight))
    setDragPos(null)
    // Browsers fire click after pointerup; a completed drag swallows it so the
    // panel doesn't toggle. Keyboard activation still lands in onOrbClick.
    suppressClickRef.current = true
  }
  const onOrbClick = (): void => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false
      return
    }
    useOrbStore.getState().toggleExpanded()
  }

  const detach = async (): Promise<void> => {
    useOrbStore.getState().setExpanded(false)
    await bridge?.detach()
    useOrbStore.getState().setDetached(true)
  }

  const orbPosition: React.CSSProperties = dragPos
    ? { left: dragPos.x - ORB_SIZE / 2, top: dragPos.y - ORB_SIZE / 2 }
    : CORNER_POS[corner]

  return (
    <>
      {expanded && (
        <div
          style={{
            position: 'fixed',
            ...PANEL_POS[corner],
            zIndex: 59,
            width: 360,
            height: 480,
            display: 'flex',
            flexDirection: 'column',
            background: 'var(--sur)',
            border: '1px solid var(--bd)',
            borderRadius: 6,
            boxShadow: '0 12px 32px rgba(0, 0, 0, 0.35)',
            overflow: 'hidden'
          }}
        >
          <PanelHeader
            onOpenScreen={() => {
              useOrbStore.getState().setExpanded(false)
              onClick()
            }}
            onDetach={bridge ? () => void detach() : null}
            onClose={() => useOrbStore.getState().setExpanded(false)}
          />
          <OrbChat projectId={project?.id ?? null} layout="panel" />
        </div>
      )}
      <div style={{ position: 'fixed', ...orbPosition, zIndex: 60 }} title="Ask SOL">
        <button
          type="button"
          aria-label="Ask SOL"
          onClick={onOrbClick}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          style={{ ...BARE_BUTTON, touchAction: 'none' }}
        >
          <SolOrb size={ORB_SIZE} pulse={pulse} />
        </button>
      </div>
    </>
  )
}
