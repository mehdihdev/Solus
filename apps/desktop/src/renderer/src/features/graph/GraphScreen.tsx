// Solus — Context Model graph screen, ported pixel-faithfully from
// TestDesign/app/graph.jsx. Alert state overlays come from the shell store;
// pure graph derivations live in ./graphModel.
import { useEffect, useMemo, useRef, useState } from 'react'
import type { Dispatch, PointerEvent as ReactPointerEvent, SetStateAction } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { DomainChip } from '../../components/ui/DomainChip'
import { SOLUS_DOMAINS, dcol, type DomainId } from '../../theme/tokens.constants'
import { ALERTS, GRAPH } from '../workspace/workspaceData.constants'
import type { Alert, GraphNode } from '../workspace/workspaceData.constants'
import { alertsWithState, useShellStore } from '../workspace/shellStore'
import { GraphInspector } from './GraphInspector'
import { GRAPH_MOTION_CSS } from './graphMotion.constants'
import {
  buildNeighbors,
  buildNodeIndex,
  clampScale,
  findOpenAlert,
  hotSetFor,
  isEdgeVisible,
  nodeWidth,
  type DomainFilter,
  type NodeIndex
} from './graphModel'

const DOMAIN_IDS: readonly DomainId[] = ['sw', 'ee', 'me', 'rt']

interface ViewState {
  s: number
  x: number
  y: number
}

interface DragOrigin {
  x: number
  y: number
  vx: number
  vy: number
}

function LoadingOverlay(): React.JSX.Element {
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        color: 'var(--mut)',
        fontFamily: 'var(--font-mono)',
        fontSize: 11
      }}
    >
      <Spinner /> LOADING CONTEXT MODEL…
    </div>
  )
}

function HullLayer({ domains }: { domains: DomainFilter }): React.JSX.Element {
  return (
    <>
      {GRAPH.hulls.map(
        (h) =>
          domains[h.d] && (
            <g key={h.d} style={{ pointerEvents: 'none' }}>
              <rect
                x={h.x}
                y={h.y}
                width={h.w}
                height={h.h}
                rx="14"
                fill={dcol(h.d)}
                opacity="0.045"
              />
              <rect
                x={h.x}
                y={h.y}
                width={h.w}
                height={h.h}
                rx="14"
                fill="none"
                stroke={dcol(h.d)}
                opacity="0.18"
                strokeDasharray="3 4"
              />
              <text
                x={h.x + 14}
                y={h.y + 20}
                fontFamily="var(--font-mono)"
                fontSize="9.5"
                letterSpacing="2"
                fill={dcol(h.d)}
                opacity="0.8"
              >
                {SOLUS_DOMAINS[h.d].label}
              </text>
            </g>
          )
      )}
    </>
  )
}

interface EdgeLayerProps {
  domains: DomainFilter
  xOnly: boolean
  byId: NodeIndex
  hotSet: ReadonlySet<string> | null
}

function EdgeLayer({ domains, xOnly, byId, hotSet }: EdgeLayerProps): React.JSX.Element {
  return (
    <>
      {GRAPH.edges.map((e, i) => {
        if (!isEdgeVisible(e, byId, domains, xOnly)) return null
        const [a, b, , hot] = e
        const A = byId[a]
        const B = byId[b]
        if (!A || !B) return null
        const dim = hotSet !== null && !(hotSet.has(a) && hotSet.has(b))
        return hot ? (
          <line
            key={i}
            x1={A.x}
            y1={A.y}
            x2={B.x}
            y2={B.y}
            stroke="var(--acc)"
            strokeWidth="1.6"
            strokeDasharray="6 5"
            opacity={dim ? 0.2 : 0.9}
            className="gm-flow"
          />
        ) : (
          <line
            key={i}
            x1={A.x}
            y1={A.y}
            x2={B.x}
            y2={B.y}
            stroke="var(--tx)"
            strokeWidth="1"
            opacity={dim ? 0.04 : 0.13}
          />
        )
      })}
    </>
  )
}

interface NodeGlyphProps {
  node: GraphNode
  index: number
  isSel: boolean
  alert: Alert | undefined
  dim: boolean
  loaded: boolean
  onSelect: (id: string | null) => void
  onHover: (id: string | null) => void
}

function NodeGlyph({
  node,
  index,
  isSel,
  alert,
  dim,
  loaded,
  onSelect,
  onHover
}: NodeGlyphProps): React.JSX.Element {
  const w = nodeWidth(node)
  return (
    <g
      className="gnode"
      transform={`translate(${node.x - w / 2}, ${node.y - 13})`}
      style={{
        cursor: 'pointer',
        opacity: loaded ? (dim ? 0.35 : 1) : 0,
        transition: `opacity 0.3s ${index * 0.025}s`
      }}
      onClick={() => onSelect(node.id)}
      onMouseEnter={() => onHover(node.id)}
      onMouseLeave={() => onHover(null)}
    >
      {isSel && (
        <rect
          x="-4"
          y="-4"
          width={w + 8}
          height="34"
          rx="8"
          fill="none"
          stroke="var(--acc)"
          strokeWidth="1.5"
        />
      )}
      <rect
        width={w}
        height="26"
        rx="5"
        fill="var(--sur2)"
        stroke={
          node.hot
            ? `color-mix(in srgb, ${dcol(node.d)} 65%, transparent)`
            : `color-mix(in srgb, ${dcol(node.d)} 32%, transparent)`
        }
        strokeWidth="1"
      />
      <circle cx="14" cy="13" r="3.2" fill={dcol(node.d)} />
      <text x="24" y="17" fontFamily="var(--font-mono)" fontSize="10.5" fill="var(--tx)">
        {node.l}
      </text>
      {alert && (
        <circle
          cx={w - 1}
          cy="1"
          r="4.5"
          fill={alert.sev === 'critical' ? 'var(--err)' : 'var(--warn)'}
          className="gm-orb"
        />
      )}
    </g>
  )
}

interface ZoomControlsProps {
  scale: number
  onZoom: (factor: number) => void
  onReset: () => void
}

function ZoomControls({ scale, onZoom, onReset }: ZoomControlsProps): React.JSX.Element {
  return (
    <div
      style={{
        position: 'absolute',
        left: 16,
        bottom: 14,
        display: 'flex',
        gap: 2,
        background: 'var(--sur)',
        border: '1px solid var(--bd)',
        borderRadius: 3,
        overflow: 'hidden'
      }}
    >
      <span
        onClick={() => onZoom(0.85)}
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 13,
          color: 'var(--mut)',
          padding: '5px 11px',
          borderRight: '1px solid var(--bd)',
          cursor: 'pointer',
          userSelect: 'none'
        }}
      >
        −
      </span>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--mut)',
          padding: '7px 10px',
          borderRight: '1px solid var(--bd)'
        }}
      >
        {Math.round(scale * 100)}%
      </span>
      <span
        onClick={() => onZoom(1.18)}
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 13,
          color: 'var(--mut)',
          padding: '5px 11px',
          borderRight: '1px solid var(--bd)',
          cursor: 'pointer',
          userSelect: 'none'
        }}
      >
        +
      </span>
      <span
        onClick={onReset}
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--mut)',
          padding: '7px 11px',
          cursor: 'pointer',
          userSelect: 'none'
        }}
      >
        ⛶
      </span>
    </div>
  )
}

interface CrossDomainToggleProps {
  xOnly: boolean
  onToggle: () => void
}

function CrossDomainToggle({ xOnly, onToggle }: CrossDomainToggleProps): React.JSX.Element {
  return (
    <div
      style={{
        position: 'absolute',
        right: 16,
        bottom: 14,
        display: 'flex',
        gap: 8,
        alignItems: 'center'
      }}
    >
      <span
        onClick={onToggle}
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          letterSpacing: '0.05em',
          padding: '5px 10px',
          borderRadius: 99,
          cursor: 'pointer',
          userSelect: 'none',
          color: xOnly ? 'var(--acc)' : 'var(--mut)',
          background: xOnly ? 'color-mix(in srgb, var(--acc) 10%, transparent)' : 'var(--sur)',
          border: `1px solid ${xOnly ? 'color-mix(in srgb, var(--acc) 40%, transparent)' : 'var(--bd)'}`
        }}
      >
        CROSS-DOMAIN ONLY
      </span>
    </div>
  )
}

interface DomainFilterBarProps {
  domains: DomainFilter
  onToggle: (d: DomainId) => void
}

function DomainFilterBar({ domains, onToggle }: DomainFilterBarProps): React.JSX.Element {
  return (
    <div
      style={{
        position: 'absolute',
        top: 12,
        left: '50%',
        transform: 'translateX(-50%)',
        display: 'flex',
        gap: 6,
        background: 'color-mix(in srgb, var(--sur) 88%, transparent)',
        backdropFilter: 'blur(6px)',
        border: '1px solid var(--bd)',
        borderRadius: 99,
        padding: '5px 8px'
      }}
    >
      {DOMAIN_IDS.map((k) => (
        <DomainChip key={k} d={k} small on={domains[k]} onClick={() => onToggle(k)} />
      ))}
    </div>
  )
}

interface CanvasSvgProps {
  view: ViewState
  loaded: boolean
  dragging: boolean
  domains: DomainFilter
  xOnly: boolean
  byId: NodeIndex
  hotSet: ReadonlySet<string> | null
  sel: string | null
  alerts: readonly Alert[]
  onSelect: (id: string | null) => void
  onHover: (id: string | null) => void
}

function CanvasSvg({
  view,
  loaded,
  dragging,
  domains,
  xOnly,
  byId,
  hotSet,
  sel,
  alerts,
  onSelect,
  onHover
}: CanvasSvgProps): React.JSX.Element {
  return (
    <svg
      width="100%"
      height="100%"
      viewBox={`0 0 ${GRAPH.vb[0]} ${GRAPH.vb[1]}`}
      preserveAspectRatio="xMidYMid meet"
      style={{
        position: 'absolute',
        inset: 0,
        opacity: loaded ? 1 : 0,
        transition: 'opacity 0.4s'
      }}
    >
      <g
        transform={`translate(${view.x},${view.y}) scale(${view.s})`}
        style={{
          transformOrigin: '550px 410px',
          transition: dragging ? 'none' : 'transform 0.18s ease-out'
        }}
      >
        <HullLayer domains={domains} />
        <EdgeLayer domains={domains} xOnly={xOnly} byId={byId} hotSet={hotSet} />
        {GRAPH.nodes.map((n, i) =>
          domains[n.d] ? (
            <NodeGlyph
              key={n.id}
              node={n}
              index={i}
              isSel={sel === n.id}
              alert={findOpenAlert(n, alerts)}
              dim={hotSet !== null && !hotSet.has(n.id)}
              loaded={loaded}
              onSelect={onSelect}
              onHover={onHover}
            />
          ) : null
        )}
      </g>
    </svg>
  )
}

/** Load-settle delay from the prototype: the model fades in after 250 ms. */
function useLoaded(): boolean {
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setLoaded(true), 250)
    return () => clearTimeout(t)
  }, [])
  return loaded
}

interface PanHandlers {
  dragging: boolean
  onDown: (e: ReactPointerEvent<HTMLDivElement>) => void
  onMove: (e: ReactPointerEvent<HTMLDivElement>) => void
  onUp: () => void
}

/** Pointer-drag panning of the canvas (nodes opt out via the .gnode class). */
function usePan(view: ViewState, setView: Dispatch<SetStateAction<ViewState>>): PanHandlers {
  const dragRef = useRef<DragOrigin | null>(null)
  const onDown = (e: ReactPointerEvent<HTMLDivElement>): void => {
    if (e.target instanceof Element && e.target.closest('.gnode')) return
    dragRef.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }
  }
  const onMove = (e: ReactPointerEvent<HTMLDivElement>): void => {
    const d = dragRef.current
    if (!d) return
    setView((v) => ({ ...v, x: d.vx + (e.clientX - d.x), y: d.vy + (e.clientY - d.y) }))
  }
  const onUp = (): void => {
    dragRef.current = null
  }
  return { dragging: dragRef.current !== null, onDown, onMove, onUp }
}

interface GraphScreenProps {
  onOpenAlert: (id: string) => void
  onAskSol: (key: string) => void
}

export function GraphScreen({ onOpenAlert, onAskSol }: GraphScreenProps): React.JSX.Element {
  const resolved = useShellStore((s) => s.resolved)
  const alerts = useMemo(() => alertsWithState(ALERTS, resolved), [resolved])
  const [sel, setSel] = useState<string | null>('drv')
  const [domains, setDomains] = useState<DomainFilter>({ sw: true, ee: true, me: true, rt: true })
  const [xOnly, setXOnly] = useState(false)
  const [view, setView] = useState<ViewState>({ s: 1, x: 0, y: 0 })
  const [hover, setHover] = useState<string | null>(null)
  const loaded = useLoaded()
  const pan = usePan(view, setView)

  const byId = useMemo(() => buildNodeIndex(GRAPH), [])
  const neighbors = useMemo(() => buildNeighbors(GRAPH), [])
  const selNode = sel ? (byId[sel] ?? null) : null
  const hotSet = hotSetFor(hover, neighbors)

  const zoom = (f: number): void => setView((v) => ({ ...v, s: clampScale(v.s * f) }))
  const toggleDomain = (k: DomainId): void => setDomains((d) => ({ ...d, [k]: !d[k] }))

  return (
    <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}>
      <style>{GRAPH_MOTION_CSS}</style>
      {/* canvas */}
      <div
        style={{
          flex: 1,
          position: 'relative',
          overflow: 'hidden',
          minWidth: 0,
          backgroundImage: 'radial-gradient(var(--bd) 1px, transparent 1px)',
          backgroundSize: '26px 26px',
          cursor: pan.dragging ? 'grabbing' : 'grab'
        }}
        onPointerDown={pan.onDown}
        onPointerMove={pan.onMove}
        onPointerUp={pan.onUp}
        onPointerLeave={pan.onUp}
      >
        {!loaded && <LoadingOverlay />}
        <CanvasSvg
          view={view}
          loaded={loaded}
          dragging={pan.dragging}
          domains={domains}
          xOnly={xOnly}
          byId={byId}
          hotSet={hotSet}
          sel={sel}
          alerts={alerts}
          onSelect={setSel}
          onHover={setHover}
        />

        <div style={{ position: 'absolute', left: 16, bottom: 52, pointerEvents: 'none' }}>
          <Mono size={10} style={{ letterSpacing: '0.08em' }}>
            247 NODES · 31 CROSS-DOMAIN LINKS · SYNCED 2 MIN AGO
          </Mono>
        </div>
        <ZoomControls scale={view.s} onZoom={zoom} onReset={() => setView({ s: 1, x: 0, y: 0 })} />
        <CrossDomainToggle xOnly={xOnly} onToggle={() => setXOnly(!xOnly)} />
        <DomainFilterBar domains={domains} onToggle={toggleDomain} />
      </div>

      <GraphInspector
        node={selNode}
        alerts={alerts}
        byId={byId}
        neighbors={neighbors}
        onSelect={setSel}
        onOpenAlert={onOpenAlert}
        onAskSol={onAskSol}
      />
    </div>
  )
}
