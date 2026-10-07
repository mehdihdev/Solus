// Workspace navigator. Graph reads, layout persistence and shared focus meet here;
// node types and rendering stay independent of provider synchronization.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FocusStep } from '@solus/shared-types'
import { WidgetRegistrationContent } from './WidgetRegistrationContent'
import { useWidgetRegistrations } from './useWidgetRegistrations'
import { isWidgetRegistration, widgetRegistrationProjection } from './widgetRegistrationProjection'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { useDetectedDevicesFeed } from './hardware/useDetectedDevicesFeed'
import type { Entity, Relation } from '../../lib/api/resources'
import type { Point } from '../../lib/api/workspace'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'
import { useFocusStore } from '../workspace/focusStore'
import { useOfflineReason, type OfflineReason } from '../workspace/workspaceOnline'
import { NodeSidebar } from './sidebar/NodeSidebar'
import { accountDocuments, isAccountAnchor, withAccountAnchors } from './accountAnchors'
import { AccountNodeContent } from './AccountNodeContent'
import { placementNearRail } from './hardware/deviceCardRules'
import { PendingDeviceCards } from './hardware/PendingDeviceCards'
import { editableRobot } from './robots/robotSession'
import { useSolusNodes } from './useSolusNodes'
import { usePhysicalRobots } from './robots/usePhysicalRobots'
import { WorkspaceAdd } from './WorkspaceAdd'
import { useWorkspaceEvents } from './useWorkspaceEvents'
import { serviceRoot, type ServiceSelection } from './serviceAttachments'
import { reconcileWorkspaceFocus } from './workspaceFocus'
import { useAuthStore } from '../../store/authStore'
import { useSettingsStore } from '../../store/settingsStore'
import { useWorkspaceGraph, type GraphSummary } from './useWorkspaceGraph'
import { useOptimisticGraph } from './useOptimisticGraph'
import { mergeOptimistic } from './graphCache'
import { useWorkspaceLayout, type MoveOrigin } from './useWorkspaceLayout'
import { RobotTopologyGraph } from './robots/RobotTopologyGraph'
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
      title: 'Your workspace will live here',
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
        'Solus builds the workspace graph from your connected tools. Connect GitHub, KiCad, or ' +
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

function useWorkspaceSelection(
  projectId: string | null,
  setSelectedAnchorId: (id: string | null) => void
) {
  return useCallback(
    (entity: Entity, ancestors: SelectionPath): void => {
      if (!projectId || useWorkspaceStore.getState().project?.id !== projectId) return
      // An account anchor is presentation only: it never enters the shared focus.
      if (isAccountAnchor(entity.id)) {
        setSelectedAnchorId(entity.id)
        return
      }
      setSelectedAnchorId(null)
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
    [projectId, setSelectedAnchorId]
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

interface AddRequest {
  tab: 'service' | 'hardware'
  sequence: number
}

interface GraphBodyProps {
  summary: ReturnType<typeof useWorkspaceGraph>
  /** The snapshot with account anchors concatenated — what the navigator draws. */
  graph: { entities: Entity[]; relations: Relation[] }
  projectId: string | null
  focusedId: string | null
  layout: WorkspaceLayout
  copy: EmptyCopy
  onSelect: (entity: Entity, ancestors: SelectionPath) => void
  onMove: (entityId: string, point: Point, origin?: MoveOrigin) => void
  onContextMenu: (event: React.MouseEvent, entity: Entity) => void
  renderContent: (entity: Entity) => React.ReactNode
  toolbar: React.ReactNode
  reveal?: { entityId: string; sequence: number }
  overlay?: React.ReactNode
  onSuggestionsChanged?: () => void
}

function WorkspaceGraphBody({
  summary,
  graph,
  projectId,
  focusedId,
  layout,
  copy,
  onSelect,
  onMove,
  onContextMenu,
  renderContent,
  toolbar,
  reveal,
  overlay,
  onSuggestionsChanged
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
    <RobotTopologyGraph
      projectId={projectId}
      entities={graph.entities}
      relations={graph.relations}
      persistDefaults={layout.status === 'ready' || layout.status === 'saving'}
      onSuggestionsChanged={onSuggestionsChanged}
      positions={layout.positions}
      focusedId={focusedId}
      reveal={reveal}
      overlay={overlay}
      onSelect={onSelect}
      onMove={onMove}
      onContextMenu={onContextMenu}
      renderContent={renderContent}
      toolbar={toolbar}
    />
  )
}

/** The bottom line: real counts, then the layout's saving/error state and the live-stream state. */
function GraphCounts({
  summary,
  layout,
  liveError
}: {
  summary: GraphSummary
  layout: WorkspaceLayout
  liveError: string | null
}): React.JSX.Element | null {
  if (summary.status !== 'ready') return null
  return (
    <div
      className="graph-status-row"
      style={{ padding: '9px 16px', flexShrink: 0, borderTop: '1px solid var(--bd)' }}
    >
      <Mono size={10} style={{ letterSpacing: '0.08em' }}>
        {graphCountsLine(summary)}
      </Mono>
      <LayoutStatus layout={layout} />
      {liveError && <span role="status">{liveError}</span>}
    </div>
  )
}

export interface WorkspaceScreenProps {
  openAddRequest?: { tab: 'hardware'; sequence: number }
  onAddRequestConsumed?: (sequence: number) => void
  onOpenBench?: () => void
  onOpenWidget?: (slug: string) => void
}

export function WorkspaceScreen(props: WorkspaceScreenProps = {}): React.JSX.Element {
  const projectId = useWorkspaceStore((state) => state.project?.id ?? null)
  const identity = useAuthStore((state) => `${state.status}:${state.user?.email ?? ''}`)
  return <ProjectWorkspace key={`${identity}:${projectId ?? ''}`} {...props} />
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

/** Seed the machine-wide device store on every stream 'ready' (a reconnect may
 *  have missed a change); offline / runner-absent stays an honest "never seeded". */

/** One-shot placement for a robot confirmed from the rail: once the id is live
 *  and has no saved position, move it near the rail — then forget it. */
function useRailPlacement(
  layout: WorkspaceLayout,
  entities: readonly Entity[] | null
): (robotId: string) => void {
  const pending = useRef(new Map<string, Point>())
  const { positions, move, status } = layout
  useEffect(() => {
    // A graph refetch re-creates the layout session; wait for its positions.
    if (!entities || (status !== 'ready' && status !== 'saving')) return
    for (const [id, point] of pending.current) {
      if (!entities.some((entity) => entity.id === id)) continue
      pending.current.delete(id)
      if (!positions[id]) move(id, point)
    }
  }, [entities, positions, move, status])
  return useCallback((robotId: string) => {
    pending.current.set(robotId, placementNearRail())
  }, [])
}

/** The canvas-edge device rail: pending devices as compact cards; a confirmed
 *  robot is shown at once (optimistic), refetched, revealed, and lands near the
 *  rail once its id is live. `entities` stays the authoritative snapshot so the
 *  placement replays when the refetch arrives (an optimistic id is never live). */
function useDeviceRail(
  projectId: string | null,
  entities: readonly Entity[] | null,
  layout: WorkspaceLayout,
  onGraphChanged: () => void,
  onReveal: (entityId: string) => void,
  onOptimistic: (entity: Entity) => void
): React.ReactNode {
  const mode = useSettingsStore((state) => state.solMode)
  const place = useRailPlacement(layout, entities)
  const robots = useMemo(
    () =>
      (entities ?? []).filter((entity) => projectId !== null && editableRobot(entity, projectId)),
    [entities, projectId]
  )
  const onCreated = useCallback(
    (robot: Entity) => {
      place(robot.id)
      onOptimistic(robot)
      onGraphChanged()
      onReveal(robot.id)
    },
    [place, onOptimistic, onGraphChanged, onReveal]
  )
  return useMemo(
    () =>
      projectId ? (
        <PendingDeviceCards
          projectId={projectId}
          mode={mode}
          robots={robots}
          entities={entities}
          onCreated={onCreated}
        />
      ) : null,
    [projectId, mode, robots, entities, onCreated]
  )
}

function useWorkspaceSnapshot() {
  const [graphRevision, setGraphRevision] = useState(0)
  const [validation, setValidation] = useState(0)
  const summary = useWorkspaceGraph(graphRevision, validation)
  const projectId = useWorkspaceStore((state) => state.project?.id ?? null)
  const { onDevices, seed } = useDetectedDevicesFeed(projectId)
  const validateGraph = useCallback(() => {
    setValidation((value) => value + 1)
    seed()
  }, [seed])
  useGraphFocusReconciliation(projectId, summary)
  const focusedId = useFocusStore((state) => state.focusedEntityId)
  // Optimistic entities join BEFORE the anchors, so a just-confirmed robot is a
  // root like a real one; the sidebar routes on this list too.
  const optimistic = useOptimisticGraph(summary.entities)
  const base = useMemo(
    () =>
      mergeOptimistic(
        { entities: summary.entities ?? [], relations: summary.relations },
        optimistic.entities
      ),
    [summary.entities, summary.relations, optimistic.entities]
  )
  // Presentation only: anchors are concatenated upstream of the unmodified index.
  const merged = useMemo(() => {
    const registered = widgetRegistrationProjection(projectId ?? '', base.entities, base.relations)
    return withAccountAnchors(registered.entities, registered.relations, summary.sources)
  }, [base, summary.sources, projectId])
  const [selectedAnchorId, setSelectedAnchorId] = useState<string | null>(null)
  // Looked up, not stored: an anchor that vanishes with its source deselects itself.
  const selectedAnchor = merged.entities.find((entity) => entity.id === selectedAnchorId) ?? null
  // Real entities only, so LayoutSession.move refuses an anchor id and never saves it.
  const liveEntityIds = useMemo(
    () => summary.entities?.map((entity) => entity.id),
    [summary.entities]
  )
  const layout = useWorkspaceLayout(projectId, summary.status === 'ready', liveEntityIds)
  const move = layout.move
  const onMove = useCallback(
    (entityId: string, point: Point, origin?: MoveOrigin) => {
      if (!isAccountAnchor(entityId)) move(entityId, point, origin)
    },
    [move]
  )
  const copy = graphEmptyCopy(summary, useOfflineReason())
  const select = useWorkspaceSelection(projectId, setSelectedAnchorId)
  const [addRequest, setAddRequest] = useState<AddRequest>()
  const onOpenAdd = useCallback(
    (tab: 'service' | 'hardware') =>
      setAddRequest((previous) => ({ tab, sequence: (previous?.sequence ?? 0) + 1 })),
    []
  )
  const onGraphChanged = useCallback((removedId?: string) => {
    setGraphRevision((revision) => revision + 1)
    const focus = useFocusStore.getState()
    if (removedId && focus.focusedEntityId === removedId) focus.clearProject()
  }, [])
  return {
    summary,
    projectId,
    onDevices,
    validateGraph,
    focusedId,
    optimistic,
    base,
    merged,
    selectedAnchor,
    layout,
    onMove,
    copy,
    select,
    addRequest,
    onOpenAdd,
    onGraphChanged
  }
}

/** Opens the add dialog once per externally issued request sequence. */
function useOpenAddRequest(
  { openAddRequest, onAddRequestConsumed }: WorkspaceScreenProps,
  onOpenAdd: (tab: 'service' | 'hardware') => void
): void {
  const handledAddSequence = useRef<number | null>(null)
  useEffect(() => {
    if (!openAddRequest || handledAddSequence.current === openAddRequest.sequence) return
    handledAddSequence.current = openAddRequest.sequence
    onOpenAdd(openAddRequest.tab)
    onAddRequestConsumed?.(openAddRequest.sequence)
  }, [openAddRequest, onAddRequestConsumed, onOpenAdd])
}

interface WorkspaceSyncInput {
  projectId: ReturnType<typeof useWorkspaceSnapshot>['projectId']
  summary: GraphSummary
  validateGraph: ReturnType<typeof useWorkspaceSnapshot>['validateGraph']
  onDevices: ReturnType<typeof useWorkspaceSnapshot>['onDevices']
}

/** Live workspace events plus widget registrations for the current project. */
function useWorkspaceSync(
  { projectId, summary, validateGraph, onDevices }: WorkspaceSyncInput,
  onGraphChanged: (removedId?: string) => void
) {
  const liveError = useWorkspaceEvents(projectId, onGraphChanged, validateGraph, onDevices)
  const registrations = useWidgetRegistrations(
    projectId,
    summary.status === 'ready',
    summary.entities,
    onGraphChanged
  )
  return { liveError, registrations }
}

function useProjectWorkspace(callbacks: WorkspaceScreenProps) {
  const {
    summary,
    projectId,
    onDevices,
    validateGraph,
    focusedId,
    optimistic,
    base,
    merged,
    selectedAnchor,
    layout,
    onMove,
    copy,
    select,
    addRequest,
    onOpenAdd,
    onGraphChanged
  } = useWorkspaceSnapshot()
  useOpenAddRequest(callbacks, onOpenAdd)
  const { liveError, registrations } = useWorkspaceSync(
    { projectId, summary, validateGraph, onDevices },
    onGraphChanged
  )
  // The reveal follows the authoritative snapshot: an entity is navigated to and
  // selected once, at its real level (an optimistic part has no parent yet).
  const { reveal, onReveal, onServiceSelected } = useWorkspaceReveal(
    summary.entities ?? [],
    onGraphChanged
  )
  const robots = usePhysicalRobots(
    projectId,
    onGraphChanged,
    onReveal,
    summary.entities,
    summary.relations,
    optimistic.add
  )
  const nodes = useSolusNodes(projectId, onGraphChanged)
  const rail = useDeviceRail(
    projectId,
    summary.entities,
    layout,
    onGraphChanged,
    onReveal,
    optimistic.add
  )
  const { renderContent, toolbar } = useWorkspaceContent(
    merged,
    robots,
    nodes,
    projectId,
    onServiceSelected,
    addRequest,
    callbacks
  )
  return {
    nodes,
    summary,
    merged,
    projectId,
    selectedAnchor,
    focusedId,
    reveal,
    rail,
    layout,
    copy,
    select,
    onMove,
    renderContent,
    toolbar,
    liveError,
    registrations,
    base,
    robots,
    onReveal,
    onOpenAdd,
    onGraphChanged
  }
}

function ProjectWorkspace(callbacks: WorkspaceScreenProps): React.JSX.Element {
  const {
    nodes,
    summary,
    merged,
    projectId,
    selectedAnchor,
    focusedId,
    reveal,
    rail,
    layout,
    copy,
    select,
    onMove,
    renderContent,
    toolbar,
    liveError,
    registrations,
    base,
    robots,
    onReveal,
    onOpenAdd,
    onGraphChanged
  } = useProjectWorkspace(callbacks)
  return (
    <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}>
      {nodes.overlays}
      <div
        style={{
          flex: 1,
          overflow: 'hidden',
          minWidth: 0,
          display: 'flex',
          flexDirection: 'column'
        }}
      >
        <WorkspaceGraphBody
          summary={summary}
          graph={merged}
          projectId={projectId}
          focusedId={selectedAnchor ? selectedAnchor.id : focusedId}
          reveal={reveal}
          overlay={rail}
          layout={layout}
          copy={copy}
          onSelect={select}
          onMove={onMove}
          onSuggestionsChanged={onGraphChanged}
          onContextMenu={nodes.onContextMenu}
          renderContent={renderContent}
          toolbar={toolbar}
        />
        <GraphCounts summary={summary} layout={layout} liveError={liveError} />
        <WidgetInitialization registrations={registrations} />
      </div>
      <NodeSidebar
        projectId={projectId}
        entity={selectedAnchor ?? base.entities.find((entity) => entity.id === focusedId) ?? null}
        robots={robots}
        nodes={nodes}
        account={{ entities: merged.entities, relations: merged.relations, onReveal, onOpenAdd }}
      />
    </div>
  )
}

function WidgetInitialization({
  registrations
}: {
  registrations: ReturnType<typeof useWidgetRegistrations>
}): React.JSX.Element | null {
  const mode = useSettingsStore((state) => state.solMode)
  if (registrations.status !== 'error' && registrations.status !== 'forbidden') return null
  return (
    <div role="status" style={{ padding: '6px 12px', fontSize: 12 }}>
      {registrations.status === 'forbidden'
        ? 'A project member must initialize widgets.'
        : mode === 'Guide'
          ? 'Could not initialize workspace widgets. Retry to make Live Bench available here.'
          : 'Widget initialization failed.'}{' '}
      <button type="button" onClick={registrations.retry}>
        Retry widget initialization
      </button>
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

function useWorkspaceContent(
  merged: ReturnType<typeof withAccountAnchors>,
  robots: ReturnType<typeof usePhysicalRobots>,
  nodes: ReturnType<typeof useSolusNodes>,
  projectId: string | null,
  onServiceSelected: ReturnType<typeof useWorkspaceReveal>['onServiceSelected'],
  addRequest: AddRequest | undefined,
  { onOpenBench, onOpenWidget }: WorkspaceScreenProps
) {
  const mode = useSettingsStore((state) => state.solMode)
  const robotContent = robots.renderContent
  const solusContent = nodes.renderContent
  // Stable per snapshot: the memoised cards re-render only when what they show changed.
  const renderContent = useCallback(
    (entity: Entity): React.ReactNode =>
      projectId && isWidgetRegistration(entity, projectId) ? (
        <WidgetRegistrationContent
          entity={entity}
          projectId={projectId}
          mode={mode}
          onOpenBench={onOpenBench}
          onOpenWidget={onOpenWidget}
        />
      ) : entity.type === 'integration_account' ? (
        <AccountNodeContent
          entity={entity}
          count={accountDocuments(entity.id, merged.entities, merged.relations).length}
        />
      ) : entity.type === 'physical_robot' || entity.type === 'robot_category' ? (
        robotContent(entity)
      ) : (
        solusContent(entity)
      ),
    [merged, robotContent, solusContent, projectId, mode, onOpenBench, onOpenWidget]
  )
  const toolbar = useMemo(
    () => (
      <WorkspaceAdd
        projectId={projectId}
        onSelected={onServiceSelected}
        hardware={robots.hardware}
        openRequest={addRequest}
      />
    ),
    [projectId, onServiceSelected, robots.hardware, addRequest]
  )
  return { renderContent, toolbar }
}
