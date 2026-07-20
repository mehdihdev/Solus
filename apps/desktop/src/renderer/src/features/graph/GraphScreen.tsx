// Context Model screen. The live graph view (canvas nodes, edges, inspector
// detail) arrives with the graph tickets; SOLUSDEV-152 removed the prototype
// demo model. The screen keeps its layout shell — dotted canvas + inspector
// rail — with an honest empty state, and shows REAL entity/relation/source
// counts from the graph API where the prototype displayed fabricated ones.
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'
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
  return {
    title: 'Your graph is taking shape',
    body:
      'Synced entities and relations are counted below. The visual context model for them ' +
      'arrives with the live graph view.'
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

export function GraphScreen(): React.JSX.Element {
  const summary = useGraphSummary()
  const copy = graphEmptyCopy(summary, useOfflineReason())

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
