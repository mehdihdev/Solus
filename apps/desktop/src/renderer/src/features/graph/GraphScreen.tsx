// Context Model screen. The full canvas view (spatial nodes, edges) is still a
// future ticket; what ships here is the WIRED slice: the project's entities as
// a selectable list over the dotted canvas, real counts in the corner, and
// selection driving the shared focus store — which re-scopes the inspector
// rail's widgets and Live Bench. SOLUSDEV-152's honesty rule stands: every
// empty state says what is actually true, never placeholder robot data.
import { useMemo } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import type { Entity } from '../../lib/api/resources'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'
import { useFocusStore } from '../workspace/focusStore'
import { useOfflineReason, type OfflineReason } from '../workspace/workspaceOnline'
import { GraphInspector } from './GraphInspector'
import { useGraphSummary, type GraphSummary } from './useGraphSummary'

interface EmptyCopy {
  title: string
  body: string
}

/** Empty-state copy for the current graph state. Pure. */
export function graphEmptyCopy(
  summary: GraphSummary,
  reason: OfflineReason = 'signed_out'
): EmptyCopy {
  if (summary.status === 'error') {
    return {
      title: "You don't have access to this project",
      body:
        'The API answered but refused this request. Switch to another project, or sign out ' +
        'and back in.'
    }
  }
  if (summary.status !== 'ready') {
    return {
      title: 'Your context model will live here',
      body:
        'Entities from your code, electronics, CAD, and runtime — and the links between them — ' +
        (reason === 'api_unreachable'
          ? "appear on this canvas. Solus can't reach its API right now — make sure the backend is running, then reload."
          : "appear on this canvas. Sign in and connect a source to start building your robot's graph.")
    }
  }
  if (summary.sourceCount === 0) {
    return {
      title: "Connect a source to start building your robot's graph",
      body:
        'Solus builds the context model from your connected tools. Connect GitHub, KiCad, or ' +
        'Onshape to this project, then run a sync — entities and cross-domain links appear here ' +
        'as sources sync.'
    }
  }
  if (summary.entityCount === 0) {
    return {
      title: 'Waiting for your first sync',
      body:
        "Your connected sources haven't produced entities yet. Run a sync and the graph starts " +
        'building itself.'
    }
  }
  // Entities exist but the list call failed — the one ready-state gap left.
  return {
    title: "Couldn't load this project's entities",
    body:
      `This project reports ${summary.entityCount} entities, but the list request failed. ` +
      'Reload to try again.'
  }
}

function countLabel(n: number, singular: string, plural: string): string {
  return `${n} ${n === 1 ? singular : plural}`
}

/** Real counts in the corner where the prototype showed fabricated ones. */
export function graphCountsLine(summary: GraphSummary): string {
  return [
    countLabel(summary.entityCount, 'ENTITY', 'ENTITIES'),
    countLabel(summary.relationCount, 'RELATION', 'RELATIONS'),
    countLabel(summary.sourceCount, 'SOURCE', 'SOURCES')
  ].join(' · ')
}

function LoadingOverlay(): React.JSX.Element {
  return (
    <div
      style={{
        flex: 1,
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

/** The project's entities as selectable rows; selection drives the shared focus. */
function EntityList({ entities }: { entities: Entity[] }): React.JSX.Element {
  const focusedId = useFocusStore((s) => s.focusedEntityId)
  const sorted = useMemo(
    () => [...entities].sort((a, b) => a.name.localeCompare(b.name)),
    [entities]
  )
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '18px 16px 44px' }}>
      <ul
        style={{
          listStyle: 'none',
          margin: 0,
          padding: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: 2
        }}
      >
        {sorted.map((entity) => {
          const focused = entity.id === focusedId
          return (
            <li key={entity.id}>
              <button
                type="button"
                onClick={() => void useFocusStore.getState().focus(entity.id)}
                aria-current={focused}
                style={{
                  width: '100%',
                  textAlign: 'left',
                  padding: '7px 10px',
                  borderRadius: 6,
                  border: `1px solid ${focused ? 'var(--acc)' : 'transparent'}`,
                  background: focused ? 'var(--sur)' : 'transparent',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: 10
                }}
              >
                <span style={{ fontSize: 13, color: 'var(--tx)' }}>{entity.name}</span>
                <Mono size={10} style={{ color: 'var(--mut)' }}>
                  {entity.type} · {entity.domain}
                </Mono>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function GraphScreen(): React.JSX.Element {
  const summary = useGraphSummary()
  const copy = graphEmptyCopy(summary, useOfflineReason())
  const showList =
    summary.status === 'ready' && summary.entityCount > 0 && summary.entities !== null

  return (
    <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}>
      <div
        style={{
          flex: 1,
          position: 'relative',
          overflow: 'hidden',
          minWidth: 0,
          display: 'flex',
          backgroundImage: 'radial-gradient(var(--bd) 1px, transparent 1px)',
          backgroundSize: '26px 26px'
        }}
      >
        {summary.status === 'loading' ? (
          <LoadingOverlay />
        ) : showList ? (
          <EntityList entities={summary.entities ?? []} />
        ) : (
          <ScreenEmptyState icon={<Icons.graph size={30} />} title={copy.title} body={copy.body} />
        )}
        {summary.status === 'ready' && (
          <div style={{ position: 'absolute', left: 16, bottom: 14, pointerEvents: 'none' }}>
            <Mono size={10} style={{ letterSpacing: '0.08em' }}>
              {graphCountsLine(summary)}
            </Mono>
          </div>
        )}
      </div>
      <GraphInspector />
    </div>
  )
}
