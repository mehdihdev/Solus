// The Home project grid (SOLUSDEV-242 / HOME H1): the active team's live
// projects as cards, a "New project" tile for members, and the archived
// section beneath. Roles come from the team summary (API.md §2.3).
import { Card } from '../../components/ui/Card'
import { Icons } from '../../components/ui/icons.constants'
import type { Project, TeamSummary } from '../../lib/api/resources'
import type { WorkspaceProject } from '../../store/workspaceStore'
import { ArchivedProjects } from './ArchivedProjects'
import { ProjectCard } from './ProjectCard'
import type { ActivityByProject } from './projectActivity'
import type { HomeActions } from './useHomeData'

/** Roles allowed to permanently delete a project — only an OWNER (ADR-025; the server enforces it). */
const MANAGER_ROLES: readonly string[] = ['owner']

export interface ProjectGridProps {
  team: TeamSummary
  projects: readonly Project[]
  activityByProject: ActivityByProject
  currentProjectId: string | null
  actions: HomeActions
  onOpenProject: (project: WorkspaceProject) => void
  onSwitchProject: (project: WorkspaceProject) => void
  onNewProject: () => void
  onActionFailed: (body: string) => void
}

export function ProjectGrid({
  team,
  projects,
  activityByProject,
  currentProjectId,
  actions,
  onOpenProject,
  onSwitchProject,
  onNewProject,
  onActionFailed
}: ProjectGridProps): React.JSX.Element {
  const canManage = team.role !== 'viewer'
  const canDelete = MANAGER_ROLES.includes(team.role)
  const live = projects.filter((p) => !p.archived_at)
  const archived = projects.filter((p) => p.archived_at)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {live.length === 0 && !canManage ? (
        <Card pad={20}>
          <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>No projects in this team yet.</div>
        </Card>
      ) : (
        <div
          data-testid="project-grid"
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
            gap: 14,
            alignItems: 'stretch'
          }}
        >
          {live.map((p) => (
            <ProjectCard
              key={p.id}
              project={p}
              activity={activityByProject[p.id] ?? []}
              currentProjectId={currentProjectId}
              canManage={canManage}
              canDelete={canDelete}
              actions={actions}
              onOpen={onOpenProject}
              onSwitch={onSwitchProject}
              onActionFailed={onActionFailed}
            />
          ))}
          {canManage && <NewProjectTile empty={live.length === 0} onClick={onNewProject} />}
        </div>
      )}
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

function NewProjectTile({
  empty,
  onClick
}: {
  empty: boolean
  onClick: () => void
}): React.JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      className="interactive"
      style={{
        minHeight: 132,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        background: 'transparent',
        border: '1px dashed var(--bd)',
        borderRadius: 6,
        color: 'var(--mut)',
        cursor: 'pointer',
        fontFamily: 'var(--font-ui)',
        fontSize: 12.5,
        padding: 16
      }}
    >
      <span style={{ color: 'var(--acc)' }}>
        <Icons.plus size={16} />
      </span>
      New project
      {empty && <span style={{ fontSize: 11 }}>Create one to start building the graph.</span>}
    </button>
  )
}
