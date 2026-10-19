// Home's left column (SOLUSDEV-317, concept B; replaces the project grid): one
// row per live project of the active team. Selecting a row makes it current
// through the switch choke point and shows it in the pane — it never opens
// the project. The ⋯ menu, the New project button and the archived section
// keep the grid's role gating (docs/wireflows/home.md "Project list").
import type { ActivityApi, Project, TeamSummary } from '../../lib/api/resources'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { relativeTime } from '../../lib/relativeTime'
import { activityText } from '../team/activityText'
import { ArchivedProjects } from './ArchivedProjects'
import { ProjectMenu } from './ProjectMenu'
import type { ActivityByProject } from './projectActivity'
import type { HomeActions } from './useHomeData'

/** Roles allowed to permanently delete a project — only an OWNER (ADR-025; the server enforces it). */
const DELETE_ROLES: readonly string[] = ['owner']

export interface HomeProjectListProps {
  team: TeamSummary
  projects: readonly Project[]
  activityByProject: ActivityByProject
  currentProjectId: string | null
  actions: HomeActions
  onSelect: (project: Project) => void
  onNewProject: () => void
  onActionFailed: (body: string) => void
}

export function HomeProjectList({
  team,
  projects,
  activityByProject,
  currentProjectId,
  actions,
  onSelect,
  onNewProject,
  onActionFailed
}: HomeProjectListProps): React.JSX.Element {
  const canManage = team.role !== 'viewer'
  const canDelete = DELETE_ROLES.includes(team.role)
  const live = projects.filter((p) => !p.archived_at)
  const archived = projects.filter((p) => p.archived_at)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', minHeight: 24 }}>
        <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
          PROJECTS · {live.length}
        </Mono>
        <div style={{ flex: 1 }} />
        {canManage && (
          <button
            type="button"
            aria-label="New project"
            className="interactive"
            onClick={onNewProject}
            style={ICON_BUTTON}
          >
            <Icons.plus size={12} />
          </button>
        )}
      </div>
      <div data-testid="project-list" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {live.map((p) => (
          <ProjectRow
            key={p.id}
            project={p}
            latest={activityByProject[p.id]?.[0] ?? null}
            isCurrent={p.id === currentProjectId}
            canManage={canManage}
            canDelete={canDelete}
            actions={actions}
            onSelect={onSelect}
            onActionFailed={onActionFailed}
          />
        ))}
        <EmptyList count={live.length} canManage={canManage} />
      </div>
      <ArchivedProjects
        projects={archived}
        canManage={canManage}
        canDelete={canDelete}
        actions={actions}
        onActionFailed={onActionFailed}
      />
    </div>
  )
}

function EmptyList({
  count,
  canManage
}: {
  count: number
  canManage: boolean
}): React.JSX.Element | null {
  if (count > 0) return null
  return (
    <div style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.5, padding: '6px 2px' }}>
      {canManage ? 'Create one to start building the graph.' : 'No projects in this team yet.'}
    </div>
  )
}

interface ProjectRowProps {
  project: Project
  latest: ActivityApi | null
  isCurrent: boolean
  canManage: boolean
  canDelete: boolean
  actions: HomeActions
  onSelect: (project: Project) => void
  onActionFailed: (body: string) => void
}

function ProjectRow({
  project,
  latest,
  isCurrent,
  canManage,
  canDelete,
  actions,
  onSelect,
  onActionFailed
}: ProjectRowProps): React.JSX.Element {
  return (
    <div
      data-testid={`project-row-${project.id}`}
      aria-current={isCurrent ? 'true' : undefined}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 4,
        borderRadius: 4,
        border: `1px solid ${isCurrent ? 'var(--acc)' : 'var(--bd)'}`,
        background: isCurrent ? 'var(--sur2)' : 'var(--sur)'
      }}
    >
      <button
        type="button"
        aria-label={`Select ${project.name}`}
        className="interactive"
        onClick={() => onSelect(project)}
        style={ROW_BUTTON}
      >
        <span style={ROW_NAME}>{project.name}</span>
        {project.description && <span style={ROW_META}>{project.description}</span>}
        <span style={ROW_META}>
          {latest
            ? `${activityText(latest)} · ${relativeTime(latest.created_at)}`
            : 'No recent activity.'}
        </span>
      </button>
      {canManage && (
        <div style={{ padding: '10px 6px 0 0' }}>
          <ProjectMenu
            project={project}
            canDelete={canDelete}
            actions={actions}
            onActionFailed={onActionFailed}
          />
        </div>
      )}
    </div>
  )
}

const ICON_BUTTON: React.CSSProperties = {
  width: 24,
  height: 24,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: 'transparent',
  border: '1px solid var(--bd)',
  borderRadius: 4,
  color: 'var(--acc)',
  cursor: 'pointer',
  padding: 0
}

const ROW_BUTTON: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  textAlign: 'left',
  background: 'transparent',
  border: 'none',
  borderRadius: 4,
  color: 'var(--tx)',
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)',
  padding: '11px 4px 11px 12px'
}

const ROW_NAME: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap'
}

const ROW_META: React.CSSProperties = {
  fontSize: 11.5,
  color: 'var(--mut)',
  lineHeight: 1.4,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap'
}
