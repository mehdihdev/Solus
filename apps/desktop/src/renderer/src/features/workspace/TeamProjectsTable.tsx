// The active team's projects on its overview (SOLUSDEV-319, multi-team Home, design D —
// docs/wireflows/home.md "Team overview"): one row per live project — name and description,
// its linked repos, the last change — where the name opens the project's pane (it never
// opens the workspace). The ⋯, New project and the archived section keep the role gating
// of the list they replace (members manage, owners delete; viewers only look).
import type { ActivityApi, Project, TeamSummary } from '../../lib/api/resources'
import { Mono } from '../../components/ui/Mono'
import { relativeTime } from '../../lib/relativeTime'
import { activityText } from '../team/activityText'
import { ArchivedProjects } from './ArchivedProjects'
import { ProjectMenu } from './ProjectMenu'
import type { ActivityByProject } from './projectActivity'
import { RepoLine } from './RepoLine'
import type { LinkedRepo, ReposByProject } from './useProjectRepos'
import type { HomeActions } from './useHomeData'

/** Only an OWNER permanently deletes a project (ADR-025; the server enforces it). */
const DELETE_ROLES: readonly string[] = ['owner']

export interface TeamProjectsTableProps {
  team: TeamSummary
  projects: readonly Project[]
  activityByProject: ActivityByProject
  reposByProject?: ReposByProject
  actions: HomeActions
  onSelect: (project: Project) => void
  onNewProject: () => void
  onActionFailed: (body: string) => void
}

export function TeamProjectsTable(props: TeamProjectsTableProps): React.JSX.Element {
  const { team, projects, actions, onActionFailed } = props
  const canManage = team.role !== 'viewer'
  const canDelete = DELETE_ROLES.includes(team.role)
  const live = projects.filter((p) => !p.archived_at)
  const archived = projects.filter((p) => p.archived_at)
  const label = team.is_personal ? 'Your projects' : `Projects in ${team.name}`
  return (
    <section style={{ display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, minHeight: 26 }}>
        <Mono size={9.5} style={{ letterSpacing: '0.08em' }}>
          PROJECTS · {live.length}
        </Mono>
        <div style={{ flex: 1 }} />
        {canManage && (
          <button
            type="button"
            className="interactive"
            onClick={props.onNewProject}
            style={NEW_BUTTON}
          >
            New project
          </button>
        )}
      </div>
      <div style={{ overflowX: 'auto', border: '1px solid var(--bd)', borderRadius: 4 }}>
        <table
          aria-label={label}
          style={{ width: '100%', minWidth: 560, borderCollapse: 'collapse' }}
        >
          <thead>
            <tr style={{ background: 'var(--sur)' }}>
              <th style={TH}>PROJECT</th>
              <th style={TH}>SOURCES</th>
              <th style={TH}>LAST CHANGE</th>
              {canManage && <th style={{ ...TH, width: 36 }} aria-label="Actions" />}
            </tr>
          </thead>
          <tbody>
            {live.map((project) => (
              <ProjectRow
                key={project.id}
                project={project}
                latest={props.activityByProject[project.id]?.[0] ?? null}
                repos={props.reposByProject?.[project.id] ?? []}
                canManage={canManage}
                canDelete={canDelete}
                actions={actions}
                onSelect={props.onSelect}
                onActionFailed={onActionFailed}
              />
            ))}
          </tbody>
        </table>
        {live.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--mut)', padding: '14px 14px' }}>
            {canManage
              ? 'Create one to start building the graph.'
              : 'No projects in this team yet.'}
          </div>
        )}
      </div>
      <ArchivedProjects
        projects={archived}
        canManage={canManage}
        canDelete={canDelete}
        actions={actions}
        onActionFailed={onActionFailed}
      />
    </section>
  )
}

interface ProjectRowProps {
  project: Project
  latest: ActivityApi | null
  repos: readonly LinkedRepo[]
  canManage: boolean
  canDelete: boolean
  actions: HomeActions
  onSelect: (project: Project) => void
  onActionFailed: (body: string) => void
}

function ProjectRow(props: ProjectRowProps): React.JSX.Element {
  const { project, latest } = props
  return (
    <tr data-testid={`project-row-${project.id}`} style={{ borderTop: '1px solid var(--bd)' }}>
      <td style={TD}>
        <button
          type="button"
          aria-label={`Open ${project.name}`}
          className="interactive"
          onClick={() => props.onSelect(project)}
          style={NAME_BUTTON}
        >
          {project.name}
        </button>
        {project.description && <div style={META}>{project.description}</div>}
      </td>
      <td style={TD}>
        {props.repos.length > 0 ? <RepoLine repos={props.repos} /> : <span style={META}>—</span>}
      </td>
      <td style={{ ...TD, ...META }}>
        {latest
          ? `${activityText(latest)} · ${relativeTime(latest.created_at)}`
          : 'No recent activity'}
      </td>
      {props.canManage && (
        <td style={{ ...TD, textAlign: 'right' }}>
          <ProjectMenu
            project={project}
            canDelete={props.canDelete}
            actions={props.actions}
            onActionFailed={props.onActionFailed}
          />
        </td>
      )}
    </tr>
  )
}

const TH: React.CSSProperties = {
  textAlign: 'left',
  fontWeight: 400,
  fontFamily: 'var(--font-mono)',
  fontSize: 9.5,
  letterSpacing: '0.08em',
  color: 'var(--mut)',
  padding: '9px 14px'
}

const TD: React.CSSProperties = { padding: '11px 14px', verticalAlign: 'top', fontSize: 12.5 }

const META: React.CSSProperties = {
  fontSize: 11.5,
  color: 'var(--mut)',
  lineHeight: 1.45,
  marginTop: 3
}

const NAME_BUTTON: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  padding: 0,
  color: 'var(--tx)',
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)',
  fontSize: 13,
  fontWeight: 600,
  textAlign: 'left'
}

const NEW_BUTTON: React.CSSProperties = {
  background: 'transparent',
  border: '1px solid var(--bd)',
  borderRadius: 4,
  color: 'var(--acc)',
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)',
  fontSize: 12,
  padding: '4px 10px'
}
