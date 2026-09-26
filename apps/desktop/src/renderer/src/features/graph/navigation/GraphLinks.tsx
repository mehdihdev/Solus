import { useState } from 'react'
import type { Entity } from '../../../lib/api/resources'
import type { Point } from '../../../lib/api/workspace'
import type { NavigationIndex, ProjectedLink } from './graphIndex'

const LINK_PAGE_SIZE = 6
const MAX_DRAWN_LINKS = 64

interface LinksProps {
  index: NavigationIndex
  links: readonly ProjectedLink[]
  onShow: (entity: Entity) => void
}

/** Real endpoints remain available even when a relation is drawn between ancestor cards. */
export function GraphLinkList({ index, links, onShow }: LinksProps): React.JSX.Element | null {
  const [requestedPage, setPage] = useState(0)
  const page = Math.min(requestedPage, Math.max(0, Math.ceil(links.length / LINK_PAGE_SIZE) - 1))
  if (links.length === 0) return null
  return (
    <details className="graph-links-list">
      <summary>
        {links.length} cross-link{links.length === 1 ? '' : 's'} · real endpoints
      </summary>
      <ul>
        {links
          .slice(page * LINK_PAGE_SIZE, (page + 1) * LINK_PAGE_SIZE)
          .map(({ relation, from, to }) => {
            const source = index.entities.get(relation.from_entity_id)
            const target = index.entities.get(relation.to_entity_id)
            if (!source || !target) return null
            return (
              <li key={relation.id}>
                <button
                  type="button"
                  onClick={() => onShow(source)}
                  aria-label={`Show linked ${source.name}`}
                >
                  {source.name}
                  {from === null ? ' ↗' : ''}
                </button>
                <span className="graph-link-type">{relation.type}</span>
                <button
                  type="button"
                  onClick={() => onShow(target)}
                  aria-label={`Show linked ${target.name}`}
                >
                  {target.name}
                  {to === null ? ' ↗' : ''}
                </button>
              </li>
            )
          })}
      </ul>
      {links.length > LINK_PAGE_SIZE && (
        <div className="graph-pagination">
          <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>
            Previous links
          </button>
          <span>
            {page * LINK_PAGE_SIZE + 1}–{Math.min((page + 1) * LINK_PAGE_SIZE, links.length)} of{' '}
            {links.length}
          </span>
          <button
            type="button"
            disabled={(page + 1) * LINK_PAGE_SIZE >= links.length}
            onClick={() => setPage(page + 1)}
          >
            Next links
          </button>
        </div>
      )}
    </details>
  )
}

interface LinkDrawingProps {
  links: readonly ProjectedLink[]
  index?: NavigationIndex
  points: Readonly<Record<string, Point>>
  offset: Point
  /** The level's anchor: the parent's point, where the parent chip sits. */
  anchor: Point
  parentName?: string
  onBack: () => void
}

export function GraphLinkDrawing({
  links,
  index,
  points,
  offset,
  anchor,
  parentName,
  onBack
}: LinkDrawingProps): React.JSX.Element {
  const local = (id: string): Point => ({ x: points[id].x - offset.x, y: points[id].y - offset.y })
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
  const unique = [...grouped.values()]
  return (
    <>
      <svg className="graph-link-drawing" role="img" aria-label="Graph relationships">
        {unique.slice(0, MAX_DRAWN_LINKS).map((group) => {
          const { relation, from, to } = group[0]
          const a = local(from!)
          const b = local(to!)
          const x = (a.x + b.x) / 2
          const y = (a.y + b.y) / 2 - 90
          const self = from === to
          const crossDomain = group.some(({ relation: edge }) => {
            const source = index?.entities.get(edge.from_entity_id)?.domain
            const target = index?.entities.get(edge.to_entity_id)?.domain
            return source !== undefined && target !== undefined && source !== target
          })
          const types = [
            ...new Set(group.map((link) => link.relation.type.replaceAll('_', ' ')))
          ].sort()
          const label = `${group.length} link${group.length === 1 ? '' : 's'} · ${types.join(', ')}`
          return (
            <g key={relation.id}>
              <path
                className={`graph-cross-edge${crossDomain ? ' graph-cross-domain-edge' : ''}`}
                d={
                  self
                    ? `M ${a.x} ${a.y} c 260 -220 260 220 0 0`
                    : `M ${a.x} ${a.y} C ${x} ${a.y - 120} ${x} ${b.y - 120} ${b.x} ${b.y}`
                }
              />
              <text
                className="graph-edge-label"
                x={self ? a.x + 195 : x}
                y={self ? a.y : y}
                textAnchor="middle"
              >
                {label}
              </text>
            </g>
          )
        })}
      </svg>
      {parentName && (
        <button
          type="button"
          className="graph-parent-anchor"
          aria-label={`Back to ${parentName}`}
          style={{ left: anchor.x - offset.x, top: 14 }}
          onClick={onBack}
        >
          {parentName}
        </button>
      )}
      {unique.length > MAX_DRAWN_LINKS && (
        <span className="graph-edge-limit">
          Drawing {MAX_DRAWN_LINKS} of {unique.length} connections; all endpoints are listed below.
        </span>
      )}
    </>
  )
}
