import { Icons } from '../../../components/ui/icons.constants'
import { Mono } from '../../../components/ui/Mono'
import type { Entity } from '../../../lib/api/resources'

export interface GraphBreadcrumbProps {
  /** Entered entities, root first (the navigator's trail). */
  trail: readonly Entity[]
  /** Cards on the current level. */
  level: number
  /** Every node the navigator knows on this canvas (account anchors included). */
  total: number
  onGo: (entity: Entity | null) => void
  onBack: () => void
}

/** The level's position and size, in the design's mono voice; counts are the navigator's own. */
export function levelStat(trail: readonly Entity[], level: number, total: number): string {
  return trail.length
    ? `${level} NODES INSIDE · ESC TO ZOOM OUT`
    : `${level} ROOTS · ${total} NODES · DOUBLE-CLICK TO ZOOM IN`
}

/** The trail as a pill — `Graph › parent › …` — with the up affordance when deeper than root. */
export function GraphBreadcrumb({
  trail,
  level,
  total,
  onGo,
  onBack
}: GraphBreadcrumbProps): React.JSX.Element {
  const crumbs: { key: string; name: string; target: Entity | null }[] = [
    { key: 'root', name: 'Graph', target: null },
    ...trail.map((entity) => ({ key: entity.id, name: entity.name, target: entity }))
  ]
  return (
    <>
      <nav className="graph-breadcrumb" aria-label="Graph trail">
        {trail.length > 0 && (
          <button type="button" aria-label="Zoom out (Esc)" title="Zoom out (Esc)" onClick={onBack}>
            <Icons.arrowL size={13} />
          </button>
        )}
        {crumbs.map((crumb, i) => (
          <span key={crumb.key} className="graph-breadcrumb-step">
            <button
              type="button"
              aria-current={i === crumbs.length - 1 ? 'location' : undefined}
              onClick={() => onGo(crumb.target)}
            >
              {crumb.name}
            </button>
            {i < crumbs.length - 1 && <i aria-hidden="true">›</i>}
          </span>
        ))}
      </nav>
      <Mono size={10} ls="0.06em" className="graph-level-stat">
        {levelStat(trail, level, total)}
      </Mono>
    </>
  )
}
