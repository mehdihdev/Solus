// Workspace navigator. Graph reads, layout persistence and shared focus meet here;
// node types and rendering stay independent of provider synchronization.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FocusStep } from '@solus/shared-types'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import type { Entity } from '../../lib/api/resources'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'
import { useFocusStore } from '../workspace/focusStore'
import { useOfflineReason, type OfflineReason } from '../workspace/workspaceOnline'
import { GraphInspector } from './GraphInspector'
import { useSolusNodes } from './useSolusNodes'
import { usePhysicalRobots } from './robots/usePhysicalRobots'
import { WorkspaceAdd } from './WorkspaceAdd'
import { useWorkspaceEvents } from './useWorkspaceEvents'
import { serviceRoot, type ServiceSelection } from './serviceAttachments'
import { reconcileWorkspaceFocus } from './workspaceFocus'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceGraph, type GraphSummary } from './useWorkspaceGraph'
import { useWorkspaceLayout } from './useWorkspaceLayout'
import { GraphNavigator } from './navigation/GraphNavigator'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { toSharedFocus } from '../workspace/useSharedFocus'

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
      <Spinner /> LOADING WORKSPACE…
    </div>
  )
}

type WorkspaceLayout = ReturnType<typeof useWorkspaceLayout>
type SelectionPath = readonly { entity: Entity; relation: string }[]

function useWorkspaceSelection(projectId: string | null) {
  return useCallback(
    (entity: Entity, ancestors: SelectionPath): void => {
      if (!projectId || useWorkspaceStore.getState().project?.id !== projectId) return
      const path: FocusStep[] = ancestors.flatMap((ancestor) => {
        const focus = toSharedFocus(ancestor.entity, projectId)
        return focus
          ? [
              {
                entity: focus.entity,
                domain: focus.domain,
                label: focus.label,
                relation: ancestor.relation
              }
            ]
          : []
      })
      void useFocusStore.getState().focus(entity.id, path)
    },
    [projectId]
  )
}

function LayoutStatus({ layout }: { layout: WorkspaceLayout }): React.JSX.Element {
  return (
    <>
      {layout.status === 'saving' && <span role="status">Saving positions…</span>}
      {layout.error && (
        <span role="alert">
          {layout.error}{' '}
          <button type="button" onClick={layout.retry}>
            Retry
          </button>
        </span>
      )}
    </>
  )
}

interface GraphBodyProps {
  summary: ReturnType<typeof useWorkspaceGraph>
  projectId: string | null
  focusedId: string | null
  layout: WorkspaceLayout
  copy: EmptyCopy
  onSelect: (entity: Entity, ancestors: SelectionPath) => void
  nodes: ReturnType<typeof useSolusNodes>
  robots: ReturnType<typeof usePhysicalRobots>
  liveError: string | null
  onServiceSelected: (selection: ServiceSelection, documentId: string) => void
  reveal?: { entityId: string; sequence: number }
}

function WorkspaceGraphBody({
  summary,
  projectId,
  focusedId,
  layout,
  copy,
  onSelect,
  nodes,
  robots,
  onServiceSelected,
  liveError,
  reveal
}: GraphBodyProps): React.JSX.Element {
  if (summary.status === 'loading') return <LoadingOverlay />
  const canRender =
    summary.status === 'ready' && summary.entityCount > 0 && summary.entities !== null
  if (!canRender || !projectId)
    return (
      <ScreenEmptyState
        icon={<Icons.graph size={30} />}
        title={copy.title}
        body={summary.errorMessage ?? copy.body}
      />
    )
  if (layout.status === 'loading') return <LoadingOverlay />
  return (
    <GraphNavigator
      projectId={projectId}
      entities={summary.entities ?? []}
      relations={summary.relations}
      positions={layout.positions}
      focusedId={focusedId}
      reveal={reveal}
      onSelect={onSelect}
      onMove={layout.move}
      onContextMenu={nodes.onContextMenu}
      renderContent={(entity) =>
        entity.type === 'physical_robot' || entity.type === 'robot_category'
          ? robots.renderContent(entity)
          : nodes.renderContent(entity)
      }
      toolbar={
        <>
          <WorkspaceAdd
            projectId={projectId}
            onSelected={onServiceSelected}
            hardware={robots.hardware}
          />
          <LayoutStatus layout={layout} />
          {liveError && <span role="status">{liveError}</span>}
        </>
      }
    />
  )
}

function GraphCounts({ summary }: { summary: GraphSummary }): React.JSX.Element | null {
  if (summary.status !== 'ready') return null
  return (
    <div style={{ padding: '9px 16px', flexShrink: 0, borderTop: '1px solid var(--bd)' }}>
      <Mono size={10} style={{ letterSpacing: '0.08em' }}>
        {graphCountsLine(summary)}
      </Mono>
    </div>
  )
}

export function WorkspaceScreen(): React.JSX.Element {
  const projectId = useWorkspaceStore((state) => state.project?.id ?? null)
  const identity = useAuthStore((state) => `${state.status}:${state.user?.email ?? ''}`)
  return <ProjectWorkspace key={`${identity}:${projectId ?? ''}`} />
}

function useWorkspaceReveal(entities: readonly Entity[], onGraphChanged: () => void) {
  const [requested, setRequested] = useState<{
    target: { sourceId: string; documentId: string } | { entityId: string }
    sequence: number
  } | null>(null)
  const onServiceSelected = useCallback(
    (selection: ServiceSelection, documentId: string): void => {
      if (selection.jobId) onGraphChanged()
      setRequested((previous) => ({
        target: { sourceId: selection.source.id, documentId },
        sequence: (previous?.sequence ?? 0) + 1
      }))
    },
    [onGraphChanged]
  )
  const onReveal = useCallback((entityId: string) => {
    setRequested((previous) => ({
      target: { entityId },
      sequence: (previous?.sequence ?? 0) + 1
    }))
  }, [])
  const target = requested?.target
  const requestedEntity =
    target &&
    ('entityId' in target
      ? entities.find((entity) => entity.id === target.entityId)
      : serviceRoot(entities, target.sourceId, target.documentId))
  const reveal =
    requestedEntity && requested
      ? { entityId: requestedEntity.id, sequence: requested.sequence }
      : undefined
  return { reveal, onReveal, onServiceSelected }
}

function ProjectWorkspace(): React.JSX.Element {
  const [graphRevision, setGraphRevision] = useState(0)
  const [validation, setValidation] = useState(0)
  const validateGraph = useCallback(() => setValidation((value) => value + 1), [])
  const summary = useWorkspaceGraph(graphRevision, validation)
  const projectId = useWorkspaceStore((state) => state.project?.id ?? null)
  useGraphFocusReconciliation(projectId, summary)
  const focusedId = useFocusStore((state) => state.focusedEntityId)
  const liveEntityIds = useMemo(
    () => summary.entities?.map((entity) => entity.id),
    [summary.entities]
  )
  const layout = useWorkspaceLayout(projectId, summary.status === 'ready', liveEntityIds)
  const copy = graphEmptyCopy(summary, useOfflineReason())
  const select = useWorkspaceSelection(projectId)
  const onGraphChanged = useCallback((removedId?: string) => {
    setGraphRevision((revision) => revision + 1)
    const focus = useFocusStore.getState()
    if (removedId && focus.focusedEntityId === removedId) focus.clearProject()
  }, [])
  const liveError = useWorkspaceEvents(projectId, onGraphChanged, validateGraph)
  const { reveal, onReveal, onServiceSelected } = useWorkspaceReveal(
    summary.entities ?? [],
    onGraphChanged
  )
  const robots = usePhysicalRobots(
    projectId,
    graphRevision,
    onGraphChanged,
    onReveal,
    summary.entities
  )
  const nodes = useSolusNodes(projectId, () => setGraphRevision((revision) => revision + 1))
  return (
    <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}>
      {nodes.overlays}
      {robots.overlays}
      <div
        style={{
          flex: 1,
          overflow: 'hidden',
          minWidth: 0,
          display: 'flex',
          flexDirection: 'column'
        }}
      >
        {summary.status === 'ready' && robots.prompt}
        <WorkspaceGraphBody
          summary={summary}
          projectId={projectId}
          focusedId={focusedId}
          reveal={reveal}
          layout={layout}
          copy={copy}
          onSelect={select}
          nodes={nodes}
          robots={robots}
          liveError={liveError}
          onServiceSelected={onServiceSelected}
        />
        <GraphCounts summary={summary} />
      </div>
      <GraphInspector />
    </div>
  )
}

function useGraphFocusReconciliation(
  projectId: string | null,
  summary: ReturnType<typeof useWorkspaceGraph>
): void {
  const previous = useRef<typeof summary.entities>(null)
  useEffect(() => {
    if (!projectId || summary.status !== 'ready' || !summary.entities) return
    const changed = previous.current !== null && previous.current !== summary.entities
    previous.current = summary.entities
    if (changed) void reconcileWorkspaceFocus(projectId, summary.entities, summary.relations)
  }, [projectId, summary.status, summary.entities, summary.relations])
}
