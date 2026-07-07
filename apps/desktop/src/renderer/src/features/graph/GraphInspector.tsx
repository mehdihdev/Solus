// Right-hand inspector panel of the Context Model screen, ported
// pixel-faithfully from the detail panel in TestDesign/app/graph.jsx.
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { KV } from '../../components/ui/KV'
import { Icons } from '../../components/ui/icons.constants'
import { SOLUS_DOMAINS, dcol, type DomainId } from '../../theme/tokens.constants'
import type { Alert, GraphNode } from '../workspace/workspaceData.constants'
import { findOpenAlert, type NeighborMap, type NodeIndex } from './graphModel'

/** External tool a node opens in, keyed by its domain (prototype ternary). */
const OPEN_TOOL: Readonly<Record<DomainId, string>> = {
  ee: 'KiCad',
  me: 'Onshape',
  sw: 'GitHub',
  rt: 'ROS'
}

interface GraphInspectorProps {
  node: GraphNode | null
  alerts: readonly Alert[]
  byId: NodeIndex
  neighbors: NeighborMap
  onSelect: (id: string | null) => void
  onOpenAlert: (id: string) => void
  onAskSol: (key: string) => void
}

export function GraphInspector(props: GraphInspectorProps): React.JSX.Element {
  return (
    <div
      style={{
        width: 318,
        borderLeft: '1px solid var(--bd)',
        background: 'var(--sur)',
        display: 'flex',
        flexDirection: 'column',
        flexShrink: 0,
        overflowY: 'auto'
      }}
    >
      {props.node ? <InspectorDetail {...props} node={props.node} /> : <InspectorEmpty />}
    </div>
  )
}

function InspectorEmpty(): React.JSX.Element {
  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        padding: 32,
        textAlign: 'center'
      }}
    >
      <span style={{ color: 'var(--mut)', opacity: 0.6 }}>
        <Icons.graph size={28} />
      </span>
      <div style={{ fontSize: 13, color: 'var(--mut)', lineHeight: 1.6 }}>
        Select a node to inspect it —<br />
        properties, sources, and its links across domains.
      </div>
    </div>
  )
}

interface AlertChipProps {
  alert: Alert
  onOpenAlert: (id: string) => void
}

function AlertChip({ alert, onOpenAlert }: AlertChipProps): React.JSX.Element {
  return (
    <div
      id="panel-alert-chip"
      onClick={() => onOpenAlert(alert.id)}
      style={{
        marginTop: 14,
        background: 'color-mix(in srgb, var(--err) 8%, transparent)',
        border: '1px solid color-mix(in srgb, var(--err) 40%, transparent)',
        borderRadius: 3,
        padding: '9px 11px',
        display: 'flex',
        gap: 9,
        alignItems: 'center',
        cursor: 'pointer'
      }}
    >
      <span
        className="gm-orb"
        style={{
          width: 7,
          height: 7,
          borderRadius: 99,
          background: 'var(--err)',
          boxShadow: '0 0 8px var(--err)',
          flexShrink: 0
        }}
      />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 11.5, fontWeight: 600 }}>{alert.title}</div>
        <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>
          {alert.actor} · {alert.time} — view alert
        </div>
      </div>
      <Icons.arrowR size={12} />
    </div>
  )
}

interface ConnectionRowProps {
  node: GraphNode
  elabel?: string
  onSelect: (id: string | null) => void
}

function ConnectionRow({ node, elabel, onSelect }: ConnectionRowProps): React.JSX.Element {
  return (
    <div
      onClick={() => onSelect(node.id)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '8px 0',
        borderBottom: '1px solid var(--bd)',
        cursor: 'pointer'
      }}
    >
      <span
        style={{ width: 6, height: 6, borderRadius: 99, background: dcol(node.d), flexShrink: 0 }}
      />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--tx)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis'
          }}
        >
          {node.l}
        </div>
        <div style={{ fontSize: 10, color: 'var(--mut)' }}>{elabel || node.sub}</div>
      </div>
      <span style={{ color: 'var(--mut)' }}>
        <Icons.arrowR size={11} />
      </span>
    </div>
  )
}

interface InspectorHeaderProps {
  node: GraphNode
  onClose: () => void
}

function InspectorHeader({ node, onClose }: InspectorHeaderProps): React.JSX.Element {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          <Mono size={9.5} color={dcol(node.d)}>
            ● {SOLUS_DOMAINS[node.d].label} · {node.type}
          </Mono>
        </div>
        <div
          style={{
            fontSize: 19,
            fontWeight: 650,
            marginTop: 6,
            letterSpacing: '-0.01em',
            fontFamily: 'var(--font-mono)'
          }}
        >
          {node.l}
        </div>
        <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 2 }}>{node.sub}</div>
      </div>
      <span
        aria-label="Close inspector"
        onClick={onClose}
        style={{ color: 'var(--mut)', cursor: 'pointer', padding: 4 }}
      >
        <Icons.x size={13} />
      </span>
    </div>
  )
}

interface InspectorDetailProps extends GraphInspectorProps {
  node: GraphNode
}

function InspectorDetail({
  node,
  alerts,
  byId,
  neighbors,
  onSelect,
  onOpenAlert,
  onAskSol
}: InspectorDetailProps): React.JSX.Element {
  const alert = findOpenAlert(node, alerts)
  const conns = (neighbors[node.id] ?? []).flatMap((c) => {
    const target = byId[c.id]
    return target ? [{ node: target, elabel: c.label }] : []
  })
  return (
    <div
      style={{
        padding: '18px 18px 14px',
        display: 'flex',
        flexDirection: 'column',
        minHeight: '100%',
        boxSizing: 'border-box'
      }}
    >
      <InspectorHeader node={node} onClose={() => onSelect(null)} />

      {alert && <AlertChip alert={alert} onOpenAlert={onOpenAlert} />}

      <div style={{ marginTop: 14 }}>
        {node.props.map(([k, v]) => (
          <KV key={k} k={k} v={v} />
        ))}
      </div>

      <Mono size={9.5} style={{ marginTop: 18, marginBottom: 2 }}>
        CONNECTED ACROSS DOMAINS
      </Mono>
      {conns.map((c) => (
        <ConnectionRow key={c.node.id} node={c.node} elabel={c.elabel} onSelect={onSelect} />
      ))}

      <div style={{ flex: 1, minHeight: 18 }} />
      <div style={{ display: 'flex', gap: 8, paddingBottom: 4 }}>
        <Button kind="ghost" style={{ flex: 1 }} size="sm">
          Open in {OPEN_TOOL[node.d]}
        </Button>
        <Button
          kind="primary"
          style={{ flex: 1 }}
          size="sm"
          onClick={() => onAskSol(node.alert ? 'alertq' : 'hello')}
        >
          Ask SOL
        </Button>
      </div>
    </div>
  )
}
