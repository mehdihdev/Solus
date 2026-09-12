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
    <details className="graph-links-list" open>
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
  points: Readonly<Record<string, Point>>
  offset: Point
  /** The level's anchor: the parent's point, where the parent chip sits. */
  anchor: Point
  parentName?: string
  onBack: () => void
}

export function GraphLinkDrawing({
  links,
  points,
  offset,
  anchor,
  parentName,
  onBack
}: LinkDrawingProps): React.JSX.Element {
  const local = (id: string): Point => ({ x: points[id].x - offset.x, y: points[id].y - offset.y })
  const seen = new Set<string>()
  const unique = links.filter((link) => {
    if (link.from === null || link.to === null) return false
    const key = [link.from, link.to].sort().join(':')
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
  return (
    <>
      <svg className="graph-link-drawing" aria-hidden="true">
        {unique.slice(0, MAX_DRAWN_LINKS).map(({ relation, from, to }) => {
          const a = local(from!)
          const b = local(to!)
          return (
            <path
              key={relation.id}
              className="graph-cross-edge"
              d={
                from === to
                  ? `M ${a.x} ${a.y} c 170 -150 170 150 0 0`
                  : `M ${a.x} ${a.y} Q ${(a.x + b.x) / 2} ${(a.y + b.y) / 2 - 60} ${b.x} ${b.y}`
              }
            />
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
