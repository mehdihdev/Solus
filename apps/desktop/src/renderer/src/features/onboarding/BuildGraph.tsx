// The Build step's graph panel (SOLUSDEV-323, docs/wireflows/onboarding.md §6):
// a legible picture of the REAL synced sources — one cluster per source in its
// domain colour, edges drawing in. Nothing synced → the honest empty line.
import { Mono } from '../../components/ui/Mono'
import { DOMAINS, domainForIntegration, type Domain } from './domainHearing'
import { graphFor, type GraphSource } from './onboardingLayout'
import type { BuildLine } from './onboardingStore'

const NODE_STAGGER_S = 0.18
const EDGE_STAGGER_S = 0.12
const EDGE_START_S = 0.6

const colorOf = (domain: Domain): string =>
  DOMAINS.find((d) => d.key === domain)?.color ?? 'var(--acc)'

/** The synced lines the picture may draw: real entities, a known domain. */
export function graphSources(lines: readonly BuildLine[]): GraphSource[] {
  return lines.flatMap((line) => {
    const domain = line.sourceType ? domainForIntegration(line.sourceType) : null
    return line.state === 'ok' && domain && line.entities
      ? [{ domain, entities: line.entities }]
      : []
  })
}

export function BuildGraph({ lines }: { lines: readonly BuildLine[] }): React.JSX.Element {
  const { nodes, edges } = graphFor(graphSources(lines))
  return (
    <div
      className="ob-rise ob-d1"
      style={{
        flex: 1,
        minHeight: 360,
        position: 'relative',
        overflow: 'hidden',
        borderRadius: 6,
        border: '1px solid var(--bd)',
        background:
          'radial-gradient(420px 300px at 50% 50%, color-mix(in srgb, var(--acc) 6%, transparent), transparent 70%), var(--sur)'
      }}
    >
      <span style={{ position: 'absolute', left: 16, top: 14 }}>
        <Mono size={9}>YOUR GRAPH</Mono>
      </span>
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden="true"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
      >
        {edges.map((e, i) => (
          <line
            key={`${e.from}-${e.to}`}
            className="ob-edge"
            pathLength={1}
            x1={nodes[e.from].x}
            y1={nodes[e.from].y}
            x2={nodes[e.to].x}
            y2={nodes[e.to].y}
            stroke={colorOf(nodes[e.to].domain)}
            strokeOpacity={0.55}
            strokeWidth={1}
            vectorEffect="non-scaling-stroke"
            style={{ animationDelay: `${EDGE_START_S + i * EDGE_STAGGER_S}s` }}
          />
        ))}
      </svg>
      {nodes.map((n, i) => (
        <span
          key={`${n.x}-${n.y}-${i}`}
          data-testid="ob-graph-node"
          data-domain={n.domain}
          className="ob-node"
          style={
            {
              left: `${n.x}%`,
              top: `${n.y}%`,
              '--ob-c': colorOf(n.domain),
              animationDelay: `${i * NODE_STAGGER_S}s`
            } as React.CSSProperties
          }
        />
      ))}
      {nodes.length === 0 && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            textAlign: 'center',
            padding: 40,
            color: 'var(--mut)',
            fontSize: 13,
            lineHeight: 1.6
          }}
        >
          Your graph draws itself here as your sources sync.
        </div>
      )}
    </div>
  )
}
