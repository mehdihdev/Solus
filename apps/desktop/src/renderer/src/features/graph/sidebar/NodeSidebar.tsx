// The right sidebar of the Workspace (SOLUSDEV-250 P4). Replaces GraphInspector and both
// delete modals: a focused node is routed by type to the hook that owns it, everything
// else gets the WS-01 widgets. Status-branched at the RAIL: while the neighbourhood fetch
// is in flight the widgets would say "Nothing focused", and on error both would print the
// same line twice. Selection never refetches the graph snapshot.
import { useEffect, type ReactNode } from 'react'
import { workspaceSessionGeneration } from '../workspaceSession'
import { getDesktopSolBridge } from '../../../lib/desktopBridge'
import { isLocalEntityKind } from '../../project/localFolder.constants'
import { LocalOpenPanel } from '../LocalOpenPanel'
import { Mono } from '../../../components/ui/Mono'
import { Spinner } from '../../../components/ui/Spinner'
import { Icons } from '../../../components/ui/icons.constants'
import type { Entity } from '../../../lib/api/resources'
import { markSafely, measureSafely } from '../../../lib/perf/marks'
import { useFocusStore } from '../../workspace/focusStore'
import { FocusSummaryWidget } from '../../workspace/widgets/FocusSummaryWidget'
import { NeighborsWidget } from '../../workspace/widgets/NeighborsWidget'
import { WidgetHost } from '../../workspace/widgets/WidgetHost'
import type { usePhysicalRobots } from '../robots/usePhysicalRobots'
import { findSolusEntry } from '../solusActions'
import type { useSolusNodes } from '../useSolusNodes'
import { AccountSidebar, type AccountSidebarProps } from './AccountSidebar'
import './sidebar.css'
import { SourceRevisionPicker } from '../SourceRevisionPicker'
import { notifySourceViewChanged } from '../sourceViewEvents'

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
}

const ROBOT_TYPES = new Set(['physical_robot', 'robot_category'])
const SOLUS_TYPES = new Set(['solus_config', 'solus_section'])

function Centered({ children }: { children: ReactNode }): React.JSX.Element {
  return <div className="node-sidebar-centered">{children}</div>
}

function route(
  entity: Entity,
  { robots, nodes, account }: Pick<NodeSidebarProps, 'robots' | 'nodes' | 'account'>
): ReactNode {
  if (ROBOT_TYPES.has(entity.type)) return robots.renderSidebar(entity)
  if (entity.type === 'integration_account')
    return account ? <AccountSidebar entity={entity} {...account} /> : null
  if (
    SOLUS_TYPES.has(entity.type) ||
    nodes.state.entityId === entity.id ||
    findSolusEntry(nodes.state.sections, entity.id)
  )
    return nodes.renderSidebar(entity)
  return null
}

function openSolSubject(entityId: string): void {
  const generation = workspaceSessionGeneration()
  void useFocusStore
    .getState()
    .focus(entityId)
    .then(() => {
      const focus = useFocusStore.getState()
      if (
        generation === workspaceSessionGeneration() &&
        focus.status === 'ready' &&
        focus.focusedEntityId === entityId
      ) {
        getDesktopSolBridge()?.open()
      }
    })
    .catch(() => undefined)
}

function EntityRail({
  projectId,
  entity
}: Pick<NodeSidebarProps, 'projectId' | 'entity'>): React.JSX.Element {
  const status = useFocusStore((s) => s.status)
  const error = useFocusStore((s) => s.error)
  if (status === 'ready')
    return (
      <div className="node-sidebar-body">
        <WidgetHost
          widget={FocusSummaryWidget}
          onSolAction={(request) => {
            if (
              projectId &&
              entity &&
              entity.type !== 'integration_account' &&
              request.kind === 'explain' &&
              request.entityId === entity.id
            )
              openSolSubject(entity.id)
          }}
        />
        {projectId && entity && isLocalEntityKind(entity.type) && (
          <LocalOpenPanel projectId={projectId} entity={entity} />
        )}
        <WidgetHost widget={NeighborsWidget} />
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

export function NodeSidebar(props: NodeSidebarProps): React.JSX.Element {
  const { entity } = props
  const owned = entity && route(entity, props)
  const status = useFocusStore((s) => s.status)
  // The heading is on screen: an owned sidebar at once, the widgets once the
  // neighbourhood is ready. Closes ws:click_to_sidebar from the card's click.
  const readyId = entity && (owned || status === 'ready') ? entity.id : null
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
  return (
    <aside className="node-sidebar" aria-label="Sidebar">
      <RepositoryRevision {...props} />
      {owned ? (
        <div className="node-sidebar-body">{owned}</div>
      ) : (
        <EntityRail projectId={props.projectId} entity={entity} />
      )}
      {entity && canAskSol(props) && (owned || status !== 'ready') && (
        <button
          type="button"
          className="node-sidebar-link"
          onClick={() => openSolSubject(entity.id)}
        >
          Ask SOL about selected node
        </button>
      )}
    </aside>
  )
}
