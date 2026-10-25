import { useState } from 'react'
import { isCandidate, relationClass } from '@solus/shared-types'
import type { Entity, Relation } from '../../../lib/api/resources'
import type { Point } from '../../../lib/api/workspace'
import type { NavigationIndex, ProjectedLink } from './graphIndex'
import { edgeSentence } from './edgeSentence'

const MAX_DRAWN_LINKS = 64
/** Vertical lift of a pair's curve; expanded bundles fan out around it. */
const CURVE_LIFT = 120
const EXPANDED_SPREAD = 36
/** Presentation-only relation ids (topologyProjection, account anchors) never select. */
const SYNTHETIC_ID = /^(topology-root|account):/

/** A containment line the level draws: the parent (or the project hub) down to a card. */
export interface StructureLine {
  from: Point
  to: Point
  /** World Y of the horizontal run; omitted = halfway between the endpoints. */
  via?: number
}

/** Orthogonal connector (design template): down from the stem, across at `via` (default
 *  halfway), down into the card. A shared `via` turns a level's drops into one bus. */
function structurePath(a: Point, b: Point, via = (a.y + b.y) / 2): string {
  return `M ${a.x} ${a.y} V ${via} H ${b.x} V ${b.y}`
}

interface LinkDrawingProps {
  links: readonly ProjectedLink[]
  index?: NavigationIndex
  points: Readonly<Record<string, Point>>
  offset: Point
  onSelectEdge?: (relation: Relation) => void
  selectedEdgeId?: string | null
  /** Containment, drawn dashed and muted behind the cards; never selectable. */
  structure?: readonly StructureLine[]
}

/** Most frequent relation type in a bundle; ties go alphabetically. */
function dominantType(group: readonly ProjectedLink[]): string {
  const counts = new Map<string, number>()
  for (const { relation } of group) counts.set(relation.type, (counts.get(relation.type) ?? 0) + 1)
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0][0]
}

/** Label rule: the dominant type with spaces, plus ` ×N` only when the bundle holds N > 1 relations. */
function bundleLabel(group: readonly ProjectedLink[]): string {
  const label = dominantType(group).replaceAll('_', ' ')
  return group.length > 1 ? `${label} ×${group.length}` : label
}

function pathData(a: Point, b: Point, lift: number): string {
  if (a.x === b.x && a.y === b.y) {
    const reach = 260 + lift - CURVE_LIFT
    return `M ${a.x} ${a.y} c ${reach} -220 ${reach} 220 0 0`
  }
  const x = (a.x + b.x) / 2
  return `M ${a.x} ${a.y} C ${x} ${a.y - lift} ${x} ${b.y - lift} ${b.x} ${b.y}`
}

interface EdgeProps {
  /** The relations this one path stands for: a whole bundle, or one of an expanded bundle. */
  group: readonly ProjectedLink[]
  index?: NavigationIndex
  a: Point
  b: Point
  lift: number
  selectedEdgeId?: string | null
  onClick: () => void
}

function EdgeGroup({
  group,
  index,
  a,
  b,
  lift,
  selectedEdgeId,
  onClick
}: EdgeProps): React.JSX.Element {
  const self = a.x === b.x && a.y === b.y
  const entity = (id: string): Entity | undefined => index?.entities.get(id)
  const crossDomain = group.some(({ relation }) => {
    const source = entity(relation.from_entity_id)?.domain
    const target = entity(relation.to_entity_id)?.domain
    return source !== undefined && target !== undefined && source !== target
  })
  const title = group
    .map(({ relation }) =>
      edgeSentence(relation, entity(relation.from_entity_id), entity(relation.to_entity_id))
    )
    .join('\n')
  return (
    <g
      data-relation-class={relationClass(dominantType(group))}
      data-candidate={
        group.every(({ relation }) => isCandidate(relation.origin, relation.confidence)) ||
        undefined
      }
      data-selected={group.some(({ relation }) => relation.id === selectedEdgeId) || undefined}
    >
      <path
        className={`graph-cross-edge${crossDomain ? ' graph-cross-domain-edge' : ''}`}
        d={pathData(a, b, lift)}
        role="button"
        tabIndex={0}
        aria-label={title}
        onClick={onClick}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            onClick()
          }
        }}
      >
        <title>{title}</title>
      </path>
      <text
        className="graph-edge-label"
        x={self ? a.x + 195 + lift - CURVE_LIFT : (a.x + b.x) / 2}
        y={self ? a.y : (a.y + b.y) / 2 - lift + 30}
        textAnchor="middle"
      >
        {bundleLabel(group)}
      </text>
    </g>
  )
}

function groupByPair(
  links: readonly ProjectedLink[],
  points: Readonly<Record<string, Point>>
): Map<string, ProjectedLink[]> {
  const grouped = new Map<string, ProjectedLink[]>()
  const seen = new Set<string>()
  for (const link of links) {
    if (
      !link.from ||
      !link.to ||
      !points[link.from] ||
      !points[link.to] ||
      seen.has(link.relation.id)
    )
      continue
    seen.add(link.relation.id)
    const key = JSON.stringify([link.from, link.to].sort())
    grouped.set(key, [...(grouped.get(key) ?? []), link])
  }
  return grouped
}

export function GraphLinkDrawing({
  links,
  index,
  points,
  offset,
  onSelectEdge,
  selectedEdgeId,
  structure = []
}: LinkDrawingProps): React.JSX.Element {
  // Expanded bundles, keyed by card pair; a level remount (new key) collapses them again.
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())
  const local = (id: string): Point => ({ x: points[id].x - offset.x, y: points[id].y - offset.y })
  const grouped = groupByPair(links, points)
  const select = (relation: Relation): void => {
    if (!SYNTHETIC_ID.test(relation.id)) onSelectEdge?.(relation)
  }
  const draw = (key: string, group: ProjectedLink[]): React.JSX.Element[] => {
    const a = local(group[0].from!)
    const b = local(group[0].to!)
    const shared = { index, a, b, selectedEdgeId }
    if (group.length > 1 && !expanded.has(key))
      return [
        <EdgeGroup
          key={group[0].relation.id}
          {...shared}
          group={group}
          lift={CURVE_LIFT}
          onClick={() => setExpanded(new Set([...expanded, key]))}
        />
      ]
    return group.map((link, position) => (
      <EdgeGroup
        key={link.relation.id}
        {...shared}
        group={[link]}
        lift={CURVE_LIFT + (position - (group.length - 1) / 2) * EXPANDED_SPREAD}
        onClick={() => select(link.relation)}
      />
    ))
  }
  return (
    <>
      <svg className="graph-link-drawing" role="group" aria-label="Graph relationships">
        {structure.map((line, i) => (
          <path
            key={`structure-${i}`}
            className="graph-structure-edge"
            d={structurePath(
              { x: line.from.x - offset.x, y: line.from.y - offset.y },
              { x: line.to.x - offset.x, y: line.to.y - offset.y },
              line.via === undefined ? undefined : line.via - offset.y
            )}
          />
        ))}
        {[...grouped].slice(0, MAX_DRAWN_LINKS).flatMap(([key, group]) => draw(key, group))}
      </svg>
      {grouped.size > MAX_DRAWN_LINKS && (
        <span className="graph-edge-limit">
          Drawing {MAX_DRAWN_LINKS} of {grouped.size} connections.
        </span>
      )}
    </>
  )
}
