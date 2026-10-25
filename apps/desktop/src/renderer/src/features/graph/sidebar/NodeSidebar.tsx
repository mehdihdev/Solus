// The right side panel of the Workspace (SOLUSDEV-250 P4, design template chrome). A
// focused node is routed by type to the hook that owns it (robots, account anchors,
// .solus); everything else gets the connections list. Every panel shares the header
// (domain dot · mono label · ✕ · title · real facts) and the footer action strip.
// Status-branched at the RAIL: while the neighbourhood fetch is in flight the body would
// be empty, and on error it would print the same line twice. Selection never refetches
// the graph snapshot.
import { useEffect, type ReactNode } from 'react'
import { Button } from '../../../components/ui/Button'
import { Mono } from '../../../components/ui/Mono'
import { Spinner } from '../../../components/ui/Spinner'
import { Icons } from '../../../components/ui/icons.constants'
import type { Entity, Relation } from '../../../lib/api/resources'
import { markSafely, measureSafely } from '../../../lib/perf/marks'
import { relativeTime } from '../../../lib/relativeTime'
import { isLocalEntityKind } from '../../project/localFolder.constants'
import { useFocusStore } from '../../workspace/focusStore'
import { LocalOpenPanel } from '../LocalOpenPanel'
import { SourceRevisionPicker } from '../SourceRevisionPicker'
import { relationWords } from '../navigation/edgeSentence'
import { findSolusEntry } from '../solusActions'
import { notifySourceViewChanged } from '../sourceViewEvents'
import type { FindingsBySubject } from '../useFindings'
import type { usePhysicalRobots } from '../robots/usePhysicalRobots'
import type { useSolusNodes } from '../useSolusNodes'
import { AccountSidebar, type AccountSidebarProps } from './AccountSidebar'
import { ConnectionsPanel } from './ConnectionsPanel'
import { EdgePanel } from './EdgePanel'
import { openSolSubject } from './openSolSubject'
import { NodePanelFooter, NodePanelHeader, panelLabel, type NodePanelMeta } from './PanelChrome'
import './sidebar.css'

export type RobotsSidebarApi = Pick<ReturnType<typeof usePhysicalRobots>, 'renderSidebar'>
export type SolusSidebarApi = Pick<ReturnType<typeof useSolusNodes>, 'renderSidebar' | 'state'>

export type AccountSidebarApi = Omit<AccountSidebarProps, 'entity'>

export interface NodeSidebarProps {
  projectId: string | null
  entity: Entity | null
  robots: RobotsSidebarApi
  nodes: SolusSidebarApi
  /** Synthetic account anchors (P5); absent while the screen is not wired for them. */
  account?: AccountSidebarApi
  /** A selected canvas edge (SOLUSDEV-320 P4-T2); takes priority over the entity. */
  edge?: EdgeSelection | null
  onEdgeDecided?: () => void
  onEdgeClose?: () => void
  /** The ✕ in the header; absent → no close affordance (tests, embedded uses). */
  onClose?: () => void
  /** A connection's node was chosen; default: focus it in place. */
  onReveal?: (entityId: string) => void
  /** Open findings per entity → the connection status pills. */
  findings?: FindingsBySubject
  /** The selected node's source type (`onshape`, `kicad`…) for the header label. */
  sourceType?: string | null
  /** "Ask SOL": default opens the SOL window with the node as subject. */
  onAskSol?: (entity: Entity) => void
}

export interface EdgeSelection {
  relation: Relation
  from?: Entity
  to?: Entity
}

const ROBOT_TYPES = new Set(['physical_robot', 'robot_category'])
const SOLUS_TYPES = new Set(['solus_config', 'solus_section', 'solus_subsection'])
const NO_FINDINGS: FindingsBySubject = new Map()

function Centered({ children }: { children: ReactNode }): React.JSX.Element {
  return <div className="node-sidebar-centered">{children}</div>
}

function isSolusNode(entity: Entity, nodes: SolusSidebarApi): boolean {
  return (
    SOLUS_TYPES.has(entity.type) ||
    nodes.state.entityId === entity.id ||
    findSolusEntry(nodes.state.sections, entity.id) !== undefined
  )
}

function route(
  entity: Entity,
  { robots, nodes, account }: Pick<NodeSidebarProps, 'robots' | 'nodes' | 'account'>,
  onAskSol: () => void
): ReactNode {
  if (ROBOT_TYPES.has(entity.type)) return robots.renderSidebar(entity)
  if (entity.type === 'integration_account')
    return account ? <AccountSidebar entity={entity} {...account} /> : null
  if (isSolusNode(entity, nodes)) return nodes.renderSidebar(entity, { onAskSol })
  return null
}

/** Only facts the record carries: SOL authorship and the entry's own timestamp. */
function solusMeta(entity: Entity, nodes: SolusSidebarApi): NodePanelMeta | undefined {
  const entry = findSolusEntry(nodes.state.sections, entity.id)
  if (!entry) return undefined
  return {
    authoredBy: entry.author === 'sol' ? 'SOL' : undefined,
    editedAgo: entry.updated_at ? relativeTime(entry.updated_at) : undefined
  }
}

function EntityRail({
  projectId,
  entity,
  findings,
  onReveal
}: Pick<NodeSidebarProps, 'projectId' | 'entity' | 'findings' | 'onReveal'>): React.JSX.Element {
  const status = useFocusStore((s) => s.status)
  const error = useFocusStore((s) => s.error)
  if (status === 'ready' && entity)
    return (
      <div className="node-sidebar-body">
        {projectId && isLocalEntityKind(entity.type) && (
          <LocalOpenPanel projectId={projectId} entity={entity} />
        )}
        <ConnectionsPanel
          entity={entity}
          findings={findings ?? NO_FINDINGS}
          onReveal={onReveal ?? ((id) => void useFocusStore.getState().focus(id))}
        />
      </div>
    )
  if (status === 'loading')
    return (
      <Centered>
        <Spinner />
        <Mono size={10} style={{ color: 'var(--mut)' }}>
          LOADING NEIGHBOURHOOD…
        </Mono>
      </Centered>
    )
  if (status === 'error') return <Centered>Could not load the neighbourhood. {error}</Centered>
  return (
    <Centered>
      <span style={{ opacity: 0.6 }}>
        <Icons.search size={26} />
      </span>
      Select an entity to inspect it — its properties, sources, and links across domains appear
      here.
    </Centered>
  )
}

function askSolFor({ onAskSol }: NodeSidebarProps, entity: Entity): void {
  if (onAskSol) onAskSol(entity)
  else openSolSubject(entity.id)
}

function canAskSol({ entity, projectId }: NodeSidebarProps): boolean {
  return Boolean(entity && entity.type !== 'integration_account' && projectId)
}

function RepositoryRevision({ entity, projectId }: NodeSidebarProps): React.JSX.Element | null {
  if (entity?.type !== 'code_repo' || !projectId) return null
  const baseSource = entity?.properties?.base_source_id
  const repositorySource = typeof baseSource === 'string' ? baseSource : entity?.source_id
  if (!repositorySource) return null
  return (
    <SourceRevisionPicker
      projectId={projectId}
      sourceId={repositorySource}
      activeSourceId={entity.source_id ?? undefined}
      onChanged={() => {
        useFocusStore.getState().clearProject()
        notifySourceViewChanged(projectId)
      }}
    />
  )
}

const noop = (): void => undefined

function EdgeRail({
  projectId,
  edge,
  onEdgeDecided = noop,
  onEdgeClose = noop,
  onClose
}: Pick<NodeSidebarProps, 'onEdgeDecided' | 'onEdgeClose' | 'onClose'> & {
  projectId: string
  edge: EdgeSelection
}): React.JSX.Element {
  const subject = edge.from ?? edge.to
  return (
    <aside className="node-sidebar" aria-label="Sidebar">
      {subject && (
        <NodePanelHeader
          entity={subject}
          label={`EDGE · ${relationWords(edge.relation.type)}`.toUpperCase()}
          onClose={onClose}
        />
      )}
      <div className="node-sidebar-body">
        <EdgePanel
          key={edge.relation.id}
          projectId={projectId}
          relation={edge.relation}
          from={edge.from}
          to={edge.to}
          onDecided={onEdgeDecided}
          onClose={onEdgeClose}
        />
      </div>
    </aside>
  )
}

/** A selected edge takes the rail over from the entity (SOLUSDEV-320 P4-T2). */
export function NodeSidebar(props: NodeSidebarProps): React.JSX.Element {
  return props.edge && props.projectId ? (
    <EdgeRail {...props} projectId={props.projectId} edge={props.edge} />
  ) : (
    <EntitySidebar {...props} />
  )
}

/** Closes ws:click_to_sidebar once the heading is on screen: an owned body at once,
 *  the connections once the neighbourhood is ready. */
function useSidebarReadyMark(readyId: string | null): void {
  useEffect(() => {
    if (!readyId) return
    markSafely('ws:sidebar_ready')
    measureSafely('ws:click_to_sidebar', 'ws:select_clicked', 'ws:sidebar_ready')
    try {
      performance.clearMarks('ws:select_clicked')
    } catch {
      // Performance instrumentation must never interrupt rendering.
    }
  }, [readyId])
}

function EntityHeader({
  entity,
  owned,
  solus,
  nodes,
  sourceType,
  onClose
}: Pick<NodeSidebarProps, 'nodes' | 'sourceType' | 'onClose'> & {
  entity: Entity
  owned: boolean
  solus: boolean
}): React.JSX.Element {
  return (
    <NodePanelHeader
      entity={entity}
      label={panelLabel(entity, sourceType ?? null)}
      title={owned ? undefined : entity.name}
      meta={solus ? solusMeta(entity, nodes) : undefined}
      onClose={onClose}
    />
  )
}

function EntitySidebar(props: NodeSidebarProps): React.JSX.Element {
  const { entity, nodes } = props
  const askSol = (): void => {
    if (entity) askSolFor(props, entity)
  }
  const owned = entity ? route(entity, props, askSol) : null
  const solus = entity ? isSolusNode(entity, nodes) : false
  const status = useFocusStore((s) => s.status)
  useSidebarReadyMark(entity && (owned || status === 'ready') ? entity.id : null)
  return (
    <aside className="node-sidebar" aria-label="Sidebar">
      {entity && (
        <EntityHeader
          entity={entity}
          owned={Boolean(owned)}
          solus={solus}
          nodes={nodes}
          sourceType={props.sourceType}
          onClose={props.onClose}
        />
      )}
      <RepositoryRevision {...props} />
      {owned ? (
        <div className="node-sidebar-body">{owned}</div>
      ) : (
        <EntityRail
          projectId={props.projectId}
          entity={entity}
          findings={props.findings}
          onReveal={props.onReveal}
        />
      )}
      <AskSolFooter show={!solus && canAskSol(props)} onAsk={askSol} />
    </aside>
  )
}

/** The design's accent footer action for every non-.solus node (its own footer carries Ask SOL). */
function AskSolFooter({
  show,
  onAsk
}: {
  show: boolean
  onAsk: () => void
}): React.JSX.Element | null {
  if (!show) return null
  return (
    <NodePanelFooter>
      <Button kind="primary" onClick={onAsk}>
        Ask SOL about this node
      </Button>
    </NodePanelFooter>
  )
}
