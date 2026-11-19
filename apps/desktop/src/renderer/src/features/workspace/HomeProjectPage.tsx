// SOLUSDEV-328 (design P2, docs/wireflows/home.md "Project page"): Home's project page, filling the
// pane like the team overview. The team's live projects are listed beside the current project
// (one click switches, the page stays), the project's folder + sources and its .solus sit side by
// side with no tabs, and its own activity is a full-height column when wide, under the project
// otherwise. Narrow, the list folds into a switcher in the header. Layout is measured on the page.
import { useRef } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icons } from '../../components/ui/icons.constants'
import { Mono } from '../../components/ui/Mono'
import type { ActivityApi, Project, TeamSummary } from '../../lib/api/resources'
import { relativeTime } from '../../lib/relativeTime'
import type { WorkspaceProject } from '../../store/workspaceStore'
import { ProjectFolderCard } from '../project/ProjectFolderCard'
import { activityText } from '../team/activityText'
import { useProjectPageLayout, type ProjectPageLayout } from './homeLayout'
import { ProjectActivityFeed } from './ProjectActivityFeed'
import { ProjectSourcesSummary } from './ProjectSourcesSummary'
import { RepoLine } from './RepoLine'
import { SolusCard } from './SolusCard'
import type { ActivityByProject } from './projectActivity'
import type { LinkedRepo } from './useProjectRepos'

/** The activity column's fixed width beside the fluid project (the team column's). */
export const PROJECT_ACTIVITY_WIDTH = 340
/** The projects list's width beside the project. */
export const PROJECT_LIST_WIDTH = 260

export interface HomeProjectPageProps {
  team: TeamSummary
  /** The team's projects; archived ones are left out here. */
  projects: readonly Project[]
  activityByProject: ActivityByProject
  /** The current project when it belongs to this team, else null. */
  current: WorkspaceProject | null
  repos: readonly LinkedRepo[]
  onSelect: (project: Project) => void
  onBack: () => void
  onNewProject: () => void
  onOpen: () => void
  onBench: () => void
  onManageSources: () => void
  /** Overrides the measured layout (tests, stories). */
  layout?: ProjectPageLayout
}

export function HomeProjectPage(props: HomeProjectPageProps): React.JSX.Element {
  const ref = useRef<HTMLDivElement>(null)
  const measured = useProjectPageLayout(ref)
  const layout = props.layout ?? measured
  const live = props.projects.filter((p) => !p.archived_at)
  const full = layout === 'full' && props.current !== null
  return (
    <div ref={ref} data-testid="project-page" data-layout={layout} style={ROOT}>
      {layout !== 'narrow' && <ProjectsList {...props} live={live} />}
      <div data-testid="project-page-detail" style={{ ...SCROLL, flex: 1 }}>
        <Detail {...props} live={live} layout={layout} />
      </div>
      {full && props.current && (
        <aside
          aria-label="Project activity"
          data-testid="project-page-activity"
          style={ACTIVITY_COLUMN}
        >
          <ActivityFeed project={props.current} team={props.team} />
        </aside>
      )}
    </div>
  )
}

type WithLive = HomeProjectPageProps & { live: readonly Project[] }

function teamLabel(team: TeamSummary): string {
  return team.is_personal ? 'Personal workspace' : team.name
}

function ProjectsList({
  team,
  live,
  current,
  onSelect,
  onBack,
  onNewProject,
  activityByProject
}: WithLive): React.JSX.Element {
  const label = team.is_personal ? 'Your projects' : `Projects in ${team.name}`
  return (
    <section style={LIST_COLUMN}>
      <div style={{ flex: 'none', display: 'grid', gap: 6, padding: '16px 16px 10px' }}>
        <BackButton team={team} onClick={onBack} />
        <Mono size={9.5} style={{ letterSpacing: '0.08em' }}>
          PROJECTS · {live.length}
        </Mono>
      </div>
      <ul aria-label={label} style={{ ...SCROLL, listStyle: 'none', margin: 0, padding: '0 8px' }}>
        {live.map((p) => (
          <li key={p.id}>
            <ProjectRow
              project={p}
              selected={p.id === current?.id}
              latest={activityByProject[p.id]?.[0]}
              onSelect={onSelect}
            />
          </li>
        ))}
      </ul>
      {team.role !== 'viewer' && (
        <div style={{ flex: 'none', padding: '12px 16px', borderTop: '1px solid var(--bd)' }}>
          <Button kind="soft" size="sm" onClick={onNewProject}>
            New project
          </Button>
        </div>
      )}
    </section>
  )
}

function ProjectRow({
  project,
  selected,
  latest,
  onSelect
}: {
  project: Project
  selected: boolean
  latest: ActivityApi | undefined
  onSelect: (project: Project) => void
}): React.JSX.Element {
  return (
    <button
      type="button"
      aria-label={`Show ${project.name}`}
      aria-current={selected ? 'true' : undefined}
      className="interactive home-card"
      onClick={() => onSelect(project)}
      style={{
        ...ROW,
        background: selected ? 'var(--sur)' : 'transparent',
        border: `1px solid ${selected ? 'var(--acc)' : 'transparent'}`
      }}
    >
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>{project.name}</span>
      <span style={{ fontSize: 11, color: 'var(--mut)' }}>
        {latest
          ? `${activityText(latest)} · ${relativeTime(latest.created_at)}`
          : 'No recent activity'}
      </span>
    </button>
  )
}

function BackButton({
  team,
  onClick
}: {
  team: TeamSummary
  onClick: () => void
}): React.JSX.Element {
  const name = teamLabel(team)
  return (
    <button
      type="button"
      aria-label={`Back to ${name}`}
      className="interactive"
      onClick={onClick}
      style={BACK}
    >
      <Icons.arrowL size={12} /> {name}
    </button>
  )
}

function Switcher({ live, current, onSelect }: WithLive): React.JSX.Element {
  // An archived or unlisted current project has no option: say "Pick a project" rather than
  // letting the select claim the first one.
  const listed = current !== null && live.some((p) => p.id === current.id)
  return (
    <select
      aria-label="Switch project"
      value={listed ? current.id : ''}
      onChange={(event) => {
        const next = live.find((p) => p.id === event.target.value)
        if (next) onSelect(next)
      }}
      style={SELECT}
    >
      {!listed && <option value="">Pick a project</option>}
      {live.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </select>
  )
}

function Detail(props: WithLive & { layout: ProjectPageLayout }): React.JSX.Element {
  const { current, layout } = props
  const narrow = layout === 'narrow'
  const description = props.projects.find((p) => p.id === current?.id)?.description ?? null
  return (
    <div style={{ display: 'grid', gap: 18, padding: '16px 24px 32px' }}>
      {narrow && (
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 }}>
          <BackButton team={props.team} onClick={props.onBack} />
          <Switcher {...props} />
          {props.team.role !== 'viewer' && (
            <Button kind="soft" size="sm" onClick={props.onNewProject}>
              New project
            </Button>
          )}
        </div>
      )}
      {current ? (
        <>
          <Header {...props} current={current} description={description} />
          <div style={PAIR}>
            <Card pad={16} style={{ minWidth: 0, display: 'grid', gap: 14 }}>
              <ProjectFolderCard
                key={current.id}
                projectId={current.id}
                heading="ON THIS COMPUTER"
                bare
              />
              <ProjectSourcesSummary project={current} onAdd={props.onManageSources} />
            </Card>
            <div style={{ minWidth: 0 }}>
              {/* Keyed: a composer or import open on one project must never carry to the next. */}
              <SolusCard key={current.id} projectId={current.id} projectName={current.name} />
            </div>
          </div>
          {layout !== 'full' && <ActivityFeed project={current} team={props.team} />}
        </>
      ) : (
        <Card pad={24}>
          <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
            Pick a project to see its folder, sources and .solus.
          </div>
        </Card>
      )}
    </div>
  )
}

function Header({
  current,
  description,
  repos,
  onOpen,
  onBench
}: WithLive & { current: WorkspaceProject; description: string | null }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 12 }}>
      <div style={{ flex: '1 1 260px', minWidth: 0 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em' }}>
          {current.name}
        </h2>
        {repos.length > 0 && (
          <div style={{ marginTop: 4 }}>
            <RepoLine repos={repos} size="md" linked />
          </div>
        )}
        {description && (
          <div style={{ marginTop: 2, fontSize: 12.5, color: 'var(--mut)' }}>{description}</div>
        )}
      </div>
      <Button kind="ghost" size="sm" onClick={onBench}>
        Live Bench
      </Button>
      <Button kind="primary" size="sm" onClick={onOpen}>
        Open workspace
      </Button>
    </div>
  )
}

/** `current` is only ever a project of `team` (the caller checks), so the team is the page's. */
function ActivityFeed({
  project,
  team
}: {
  project: WorkspaceProject
  team: TeamSummary
}): React.JSX.Element {
  return <ProjectActivityFeed project={{ id: project.id, teamId: team.team_id }} />
}

const SCROLL: React.CSSProperties = { minWidth: 0, minHeight: 0, overflowY: 'auto' }

const ROOT: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  minHeight: 0,
  display: 'flex',
  overflow: 'hidden'
}

const LIST_COLUMN: React.CSSProperties = {
  flex: `0 0 ${PROJECT_LIST_WIDTH}px`,
  minHeight: 0,
  display: 'flex',
  flexDirection: 'column',
  borderRight: '1px solid var(--bd)'
}

const ACTIVITY_COLUMN: React.CSSProperties = {
  ...SCROLL,
  flex: `0 0 ${PROJECT_ACTIVITY_WIDTH}px`,
  padding: 16,
  boxSizing: 'border-box',
  borderLeft: '1px solid var(--bd)',
  background: 'var(--sur)'
}

const PAIR: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 420px), 1fr))',
  gap: 16,
  alignItems: 'start'
}

const ROW: React.CSSProperties = {
  display: 'grid',
  gap: 4,
  width: '100%',
  textAlign: 'left',
  padding: 10,
  marginBottom: 2,
  borderRadius: 4,
  color: 'var(--tx)',
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)'
}

const BACK: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  justifySelf: 'start',
  margin: '0 0 0 -6px',
  background: 'transparent',
  border: 'none',
  borderRadius: 4,
  color: 'var(--acc)',
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)',
  fontSize: 12.5,
  padding: '4px 6px'
}

const SELECT: React.CSSProperties = {
  background: 'var(--sur)',
  border: '1px solid var(--bd)',
  borderRadius: 4,
  color: 'var(--tx)',
  fontFamily: 'var(--font-ui)',
  fontSize: 12.5,
  padding: '5px 8px'
}
