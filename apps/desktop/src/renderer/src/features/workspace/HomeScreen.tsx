// Home (SOLUSDEV-242 / HOME H1 → H5; SOLUSDEV-317 layout; SOLUSDEV-319 multi-team, design
// D): the cross-project AND cross-team surface. A team rail lists every team I belong to
// (switch in one click, create, join, answer invitations) above the ACCOUNT nav; the pane
// shows the active team's overview (projects, members, me in it) by default, one of its
// projects when picked, the members view (roster, invites, GitHub org, team feed) or
// connected accounts. Offline (dev bypass / unreachable API) shows an honest sign-in state —
// never a demo project (SOLUSDEV-152); a team that is gone says so.
import './home.css'
import { useCallback, useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { useWorkspaceStore, type WorkspaceProject } from '../../store/workspaceStore'
import type { Project } from '../../lib/api/resources'
import { personalTeam } from '../../lib/api/resources'
import { MANAGER_ROLES } from '../team/MembersPanel'
import { TeamInvitesView } from '../teamInvites/TeamInvitesView'
import { displayName, useMe } from './useMe'
import { useHomeData, type HomeData } from './useHomeData'
import { useHomeTeam, type HomeTeam } from './useHomeTeam'
import { switchWorkspaceProject } from './projectSwitch'
import { useOfflineReason } from './workspaceOnline'
import { useShellStore, type MainScreen } from './shellStore'
import { NameModal } from './modals'
import { ConnectedAccountsCard } from './ConnectedAccountsCard'
import { GitHubInviteTokenHost } from './githubInviteTokenStore'
import { HomeAccountNav, type AccountsPosition, type HomePaneView } from './HomeAccountNav'
import { useAccountConnections } from './useAccountConnections'
import { linkedRepos, useProjectRepos, type ReposByProject } from './useProjectRepos'
import { useProjectSources } from '../project/useProjectSources'
import { HomeProjectPane } from './HomeProjectPane'
import { HomeTeamModals, type HomeTeamModal } from './HomeTeamModals'
import { TeamOverview } from './TeamOverview'
import { TeamProjectsTable } from './TeamProjectsTable'
import { TeamRail } from './TeamRail'
import { useMyInvites, type MyInvites } from './useMyInvites'
import { useTeamSizes, type TeamSizes } from './useTeamSizes'

export interface HomeScreenProps {
  onOpenProject: (project: WorkspaceProject) => void
  /** Rail navigation (Sources from the accounts card; Billing from a plan limit). */
  onNavigate?: (screen: MainScreen) => void
}

/** The offline and gone states keep a centred column up to this width. */
const HOME_MAX_WIDTH = 1480

/** The pane's content stops growing here, so wide windows don't stretch
 *  three cards into thin strips of text. */
const PANE_MAX_WIDTH = 1180

/** Selecting a project row makes it current and stays on Home — the same
 *  choke point as every other switch (SOLUSDEV-242), no navigation. */
function switchHomeProject(project: Project): void {
  switchWorkspaceProject({ id: project.id, name: project.name, teamId: project.team_id }, 'home')
}

/** Surface a failed background mutation (archive/unarchive) via the shell toast. */
function toastActionFailed(body: string): void {
  useShellStore.getState().setToast({ kind: 'warn', title: "That didn't work", body })
}

export function HomeScreen({ onOpenProject, onNavigate }: HomeScreenProps): React.JSX.Element {
  const me = useMe()
  const home = useHomeData()
  const greeting = `Welcome back, ${displayName(me.name, me.email)}`
  // A Settings deep link (SOLUSDEV-318) is consumed by LiveHome; if Home
  // settles offline or gone instead, drop it so a later visit isn't hijacked.
  const settled = home.status !== 'loading' && home.status !== 'ready'
  useEffect(() => {
    if (settled) useShellStore.getState().clearHomeView()
  }, [settled])

  if (home.status === 'loading') {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spinner size={20} />
      </div>
    )
  }

  if (home.status === 'ready')
    return (
      <LiveHome
        home={home}
        greeting={greeting}
        onOpenProject={onOpenProject}
        onNavigate={onNavigate}
      />
    )

  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: HOME_MAX_WIDTH, margin: '0 auto', padding: '26px 24px 48px' }}>
        <Greeting text={greeting} />
        {home.status === 'offline' && <OfflineHome />}
        {home.status === 'gone' && <GoneHome home={home} />}
      </div>
    </div>
  )
}

function Greeting({ text }: { text: string }): React.JSX.Element {
  return (
    <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600, letterSpacing: '-0.015em' }}>{text}</h1>
  )
}

interface LiveProps {
  home: HomeData
  greeting: string
  team: HomeTeam
  currentProject: WorkspaceProject | null
  view: HomePaneView
  onShow: (view: HomePaneView) => void
  onOpenProject: HomeScreenProps['onOpenProject']
  onNavigate: HomeScreenProps['onNavigate']
  openModal: (modal: HomeTeamModal) => void
  onUpgrade: (() => void) | undefined
  /** Linked git repos per live project, shared by the list and the pane. */
  repos: ReposByProject
  /** Connected accounts was opened from the project ("Add additional sources"). */
  backToProject: boolean
  /** Open Connected accounts from the project, with a way back. */
  onAddSources: () => void
  onNewProject: () => void
  invites: MyInvites
  sizes: TeamSizes
}

function Sidebar(props: LiveProps): React.JSX.Element {
  const { home, team, view, onShow, openModal } = props
  const accounts = useAccountsPosition(view)
  return (
    <TeamRail
      greeting={props.greeting}
      teams={home.teams}
      activeTeamId={home.team?.team_id ?? null}
      sizes={props.sizes}
      invites={props.invites}
      teamLimit={team.teamLimit}
      onSwitch={(teamId) => {
        if (teamId !== home.team?.team_id) home.actions.switchTeam(teamId)
        onShow('team')
      }}
      onNewTeam={() => openModal('newTeam')}
      onJoin={() => openModal('join')}
      onUpgrade={props.onUpgrade}
      footer={
        <HomeAccountNav
          view={view}
          team={
            team.status === 'ready'
              ? { members: team.members.length, pending: team.invites.length }
              : null
          }
          accounts={accounts}
          onShow={onShow}
        />
      }
    />
  )
}

/** Each live project's linked repos — read once per project, with the current
 *  project's taken from its live source list so a repo picked here shows at once. */
function useReposByProject(home: HomeData, currentId: string | null): ReposByProject {
  const ids = home.projects.filter((p) => !p.archived_at).map((p) => p.id)
  const read = useProjectRepos(ids)
  const live = useProjectSources()
  if (!currentId || live.status !== 'ready') return read
  return { ...read, [currentId]: linkedRepos(live.sources) }
}

/** "← Back to <project>" above Connected accounts when it was opened from there. */
function BackToProject({
  name,
  onClick
}: {
  name: string
  onClick: () => void
}): React.JSX.Element {
  return (
    <button
      type="button"
      aria-label={`Back to ${name}`}
      className="interactive"
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        margin: '0 0 14px -6px',
        background: 'transparent',
        border: 'none',
        borderRadius: 4,
        color: 'var(--acc)',
        cursor: 'pointer',
        fontFamily: 'var(--font-ui)',
        fontSize: 12.5,
        padding: '4px 6px'
      }}
    >
      <Icons.arrowL size={12} /> Back to {name}
    </button>
  )
}

/** Linked account grants by health for the ACCOUNT card; null until known. */
function useAccountsPosition(view: HomePaneView): AccountsPosition | null {
  const { status, connections, refresh } = useAccountConnections()
  // The pane's own cards hold their own copy of the grants: re-read when the
  // view changes so a link or revoke made there shows here too.
  useEffect(() => {
    void refresh()
  }, [view, refresh])
  if (status !== 'ready') return null
  const live = connections.filter((c) => c.status !== 'revoked')
  const healthy = live.filter((c) => c.status === 'connected' && c.health === 'healthy').length
  return { healthy, attention: live.length - healthy }
}

function Pane(props: LiveProps): React.JSX.Element {
  return (
    <main
      data-testid="home-pane"
      aria-label="Details"
      style={{ flex: 1, minWidth: 0, overflowY: 'auto' }}
    >
      {/* Keyed to what it shows, so each switch of view or project eases in. */}
      <div
        key={`${props.view}:${props.currentProject?.id ?? ''}`}
        className="home-pane-in"
        style={{ maxWidth: PANE_MAX_WIDTH, padding: '26px 32px 48px' }}
      >
        {props.view === 'team' && <TeamView {...props} />}
        {props.view === 'members' && <MembersView {...props} />}
        {props.view === 'accounts' && (
          <>
            {props.backToProject && props.currentProject && (
              <BackToProject
                name={props.currentProject.name}
                onClick={() => props.onShow('project')}
              />
            )}
            {/* OAuth binds at ACCOUNT scope (SOLUSDEV-241): link a tool account
                here once; each project picks what it tracks from the same card. */}
            <ConnectedAccountsCard
              currentProject={props.currentProject}
              onNavigate={props.onNavigate}
            />
          </>
        )}
        {props.view === 'project' && (
          <>
            {props.home.team && (
              <BackToProject
                name={teamName(props.home.team)}
                onClick={() => props.onShow('team')}
              />
            )}
            <ProjectView {...props} />
          </>
        )}
      </div>
    </main>
  )
}

function ProjectView({
  home,
  repos,
  currentProject,
  onAddSources,
  onOpenProject,
  onNavigate
}: LiveProps): React.JSX.Element {
  if (!currentProject)
    return (
      <Card pad={24}>
        <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
          Pick a project from the team overview to see its folder, sources and .solus.
        </div>
      </Card>
    )
  const project = home.projects.find((p) => p.id === currentProject.id)
  return (
    <HomeProjectPane
      key={currentProject.id}
      project={currentProject}
      description={project?.description ?? null}
      activity={home.activityByProject[currentProject.id] ?? []}
      repos={repos[currentProject.id] ?? []}
      onOpen={() => onOpenProject(currentProject)}
      onBench={() => onNavigate?.('bench')}
      onManageSources={onAddSources}
    />
  )
}

function teamName(team: { name: string; is_personal: boolean }): string {
  return team.is_personal ? 'Personal workspace' : team.name
}

/** SOLUSDEV-319 (design D): the active team's overview, Home's default pane. */
function TeamView(props: LiveProps): React.JSX.Element {
  const { home, team, repos, openModal, onShow } = props
  if (home.team === null)
    return (
      <Card pad={24}>
        <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
          You&apos;re not on any teams yet. Create one, or join with an invite code.
        </div>
      </Card>
    )
  const projects = (
    <TeamProjectsTable
      team={home.team}
      projects={home.projects}
      activityByProject={home.activityByProject}
      reposByProject={repos}
      actions={home.actions}
      onSelect={(p) => {
        switchHomeProject(p)
        onShow('project')
      }}
      onNewProject={props.onNewProject}
      onActionFailed={toastActionFailed}
    />
  )
  return (
    <TeamOverview
      key={home.team.team_id}
      team={home.team}
      homeTeam={team}
      meId={home.me?.id ?? null}
      projectCount={home.projects.filter((p) => !p.archived_at).length}
      projects={projects}
      menu={{
        onJoin: () => openModal('join'),
        onNewTeam: () => openModal('newTeam'),
        onInvite: () => openModal('invite'),
        onRename: () => openModal('rename'),
        onLeave: () => openModal('leave'),
        onDelete: () => openModal('delete')
      }}
      onInvite={() => openModal('invite')}
      onJoin={() => openModal('join')}
      onManageMembers={() => onShow('members')}
    />
  )
}

/** SOLUSDEV-317 (design A): one roster — the team, its invites and (for admins
 *  with an Organization link) the GitHub org, beside the team activity rail.
 *  Keyed by team, so a switch starts clean. */
function MembersView({ home, team, onUpgrade, openModal }: LiveProps): React.JSX.Element {
  const canManage = team.myRole !== null && MANAGER_ROLES.includes(team.myRole)
  if (home.team === null || team.status !== 'ready')
    return (
      <Card pad={20}>
        <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>Loading the team…</div>
      </Card>
    )
  return (
    <TeamInvitesView
      key={home.team.team_id}
      team={home.team}
      homeTeam={team}
      canManage={canManage}
      onInvite={() => openModal('invite')}
      onUpgrade={onUpgrade}
    />
  )
}

/** A Settings deep link (SOLUSDEV-318) picks the first pane; read once,
 *  cleared in an effect so a StrictMode double-render still sees it. */
function useInitialHomeView(): [HomePaneView, (next: HomePaneView) => void] {
  const [view, setView] = useState<HomePaneView>(() => useShellStore.getState().homeView ?? 'team')
  useEffect(() => useShellStore.getState().clearHomeView(), [])
  return [view, setView]
}

/** The member counts already known: the open team's, from its loaded roster. */
function loadedSizes(home: HomeData, team: HomeTeam): Record<string, number> {
  if (home.team === null || team.status !== 'ready') return {}
  return { [home.team.team_id]: team.members.length }
}

function NewProjectModal({
  home,
  onOpenProject,
  onClose
}: {
  home: HomeData
  onOpenProject: HomeScreenProps['onOpenProject']
  onClose: () => void
}): React.JSX.Element {
  return (
    <NameModal
      title="New project"
      label="Project name"
      submitLabel="Create"
      errorText="Couldn't create the project. Check your access and try again."
      onClose={onClose}
      onSubmit={async (name) => {
        const created = await home.actions.createProject(name)
        if (created) onOpenProject({ id: created.id, name: created.name, teamId: created.team_id })
        return created !== null
      }}
    />
  )
}

function LiveHome({
  home,
  greeting,
  onOpenProject,
  onNavigate
}: {
  home: HomeData
  greeting: string
  onOpenProject: HomeScreenProps['onOpenProject']
  onNavigate: HomeScreenProps['onNavigate']
}): React.JSX.Element {
  const currentProject = useWorkspaceStore((s) => s.project)
  const team = useHomeTeam(home.team, home.me, home.actions.refresh)
  const [creatingProject, setCreatingProject] = useState(false)
  const [modal, setModal] = useState<HomeTeamModal>(null)
  const [view, setView] = useInitialHomeView()
  const [backToProject, setBackToProject] = useState(false)
  // Any navigation clears the way back; only "Add additional sources" sets it.
  const show = (next: HomePaneView): void => {
    setBackToProject(false)
    setView(next)
  }
  const repos = useReposByProject(home, currentProject?.id ?? null)
  const switchTeam = home.actions.switchTeam
  // An accepted invitation lands me on the team I joined.
  const onJoined = useCallback(
    (teamId: string) => {
      switchTeam(teamId)
      setBackToProject(false)
      setView('team')
    },
    [switchTeam, setView]
  )
  const invites = useMyInvites(onJoined)
  const sizes = useTeamSizes(
    home.teams.map((t) => t.team_id),
    loadedSizes(home, team)
  )
  const onUpgrade = onNavigate ? () => onNavigate('billing') : undefined
  const live: LiveProps = {
    home,
    greeting,
    team,
    currentProject,
    view,
    onShow: show,
    backToProject,
    onAddSources: () => {
      setView('accounts')
      setBackToProject(true)
    },
    onOpenProject,
    onNavigate,
    openModal: setModal,
    onUpgrade,
    repos,
    onNewProject: () => setCreatingProject(true),
    invites,
    sizes
  }

  return (
    <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}>
      <Sidebar {...live} />
      <Pane {...live} />
      {creatingProject && (
        <NewProjectModal
          home={home}
          onOpenProject={onOpenProject}
          onClose={() => setCreatingProject(false)}
        />
      )}
      {/* Outlives the org members section (team switch, demotion): only Done discards it. */}
      <GitHubInviteTokenHost />
      <HomeTeamModals
        modal={modal}
        teamName={home.team?.name ?? null}
        isPersonal={home.team?.is_personal ?? false}
        home={home.actions}
        team={team}
        onClose={() => setModal(null)}
        onUpgrade={onUpgrade}
      />
    </div>
  )
}

/** The stored team no longer exists (deleted, or I was removed) — the API is
 *  answering, so this is not an outage. One click lands on the personal team. */
function GoneHome({ home }: { home: HomeData }): React.JSX.Element {
  const personal = home.me ? personalTeam(home.me) : undefined
  return (
    <Card pad={20} style={{ marginTop: 16 }}>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
        This team is no longer available — it was deleted, or you were removed from it.
      </div>
      <div style={{ marginTop: 12 }}>
        <Button
          kind="soft"
          size="sm"
          onClick={() => personal && home.actions.switchTeam(personal.team_id)}
        >
          Go to my personal workspace
        </Button>
      </div>
    </Card>
  )
}

/** Honest offline state (dev bypass / unreachable API) — never a demo project. */
function OfflineHome(): React.JSX.Element {
  const reason = useOfflineReason()
  return (
    <div style={{ marginTop: 16 }}>
      <Card pad={20}>
        <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
          {reason === 'api_unreachable'
            ? "You're signed in, but Solus can't reach its API. Make sure the backend is running, then reload — your teams, projects, and recent activity will appear here."
            : 'Sign in to Solus to see your teams, projects, and recent activity here.'}
        </div>
      </Card>
    </div>
  )
}
