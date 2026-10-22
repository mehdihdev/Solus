// Home (SOLUSDEV-242 / HOME H1 → H5; SOLUSDEV-317 layout, concept B): the
// cross-project AND cross-team surface. The active team is always visible
// (the strip), with the switcher only when the user belongs to more than one
// team. Beneath it, two columns: the team's projects as a list (selecting one
// makes it current) with the ACCOUNT nav, and ONE pane showing the current
// project (folder, sources, activity, .solus), the members view (roster,
// invites, GitHub org, team feed) or connected accounts. Offline (dev bypass /
// unreachable API) shows an honest sign-in state — never a demo project
// (SOLUSDEV-152); a team that is gone says so — never "restart the backend".
import './home.css'
import { useEffect, useState } from 'react'
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
import { HomeProjectList } from './HomeProjectList'
import { HomeProjectPane } from './HomeProjectPane'
import { HomeTeamModals, type HomeTeamModal } from './HomeTeamModals'
import { TeamStrip } from './TeamStrip'

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

/** Concept B's sidebar: full height, its own scroll, the ACCOUNT card at its foot. */
const SIDEBAR_STYLE: React.CSSProperties = {
  flex: '0 0 300px',
  width: 300,
  display: 'flex',
  flexDirection: 'column',
  gap: 22,
  padding: '26px 20px 20px',
  borderRight: '1px solid var(--bd)',
  overflowY: 'auto',
  // Never a sideways scrollbar: anything wider than the sidebar is a bug to fix.
  overflowX: 'hidden',
  minHeight: 0
}

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
}

function Sidebar(props: LiveProps): React.JSX.Element {
  const { home, team, currentProject, view, onShow, openModal, onNewProject } = props
  const accounts = useAccountsPosition(view)
  const { repos } = props
  return (
    <aside aria-label="Projects" style={SIDEBAR_STYLE}>
      <div style={{ display: 'grid', gap: 12 }}>
        <Greeting text={props.greeting} />
        <TeamStrip
          team={home.team}
          teams={home.teams}
          memberCount={memberCount(team)}
          myRole={team.myRole}
          teamLimit={team.teamLimit}
          onSwitch={home.actions.switchTeam}
          onJoin={() => openModal('join')}
          onNewTeam={() => openModal('newTeam')}
          onInvite={() => openModal('invite')}
          onRename={() => openModal('rename')}
          onLeave={() => openModal('leave')}
          onDelete={() => openModal('delete')}
          onUpgrade={props.onUpgrade}
        />
      </div>
      {home.team ? (
        <HomeProjectList
          team={home.team}
          projects={home.projects}
          activityByProject={home.activityByProject}
          reposByProject={repos}
          currentProjectId={currentProject?.id ?? null}
          actions={home.actions}
          onSelect={(p) => {
            switchHomeProject(p)
            onShow('project')
          }}
          onNewProject={onNewProject}
          onActionFailed={toastActionFailed}
        />
      ) : (
        <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
          You&apos;re not on any teams yet. Create one, or join with an invite token.
        </div>
      )}
      <div style={{ flex: 1 }} />
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
    </aside>
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
        {props.view === 'project' && <ProjectView {...props} />}
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
          Select a project on the left to see its folder, sources and .solus.
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

/** The strip's member count: the live roster once loaded (a removal updates
 *  it at once); the detail's count only until then. */
function memberCount(team: HomeTeam): number | null {
  if (team.status === 'ready') return team.members.length
  return team.detail?.member_count ?? null
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
  // A Settings deep link (SOLUSDEV-318) picks the first pane; read here, cleared
  // in an effect so a StrictMode double-render still sees it.
  const [view, setView] = useState<HomePaneView>(
    () => useShellStore.getState().homeView ?? 'project'
  )
  useEffect(() => useShellStore.getState().clearHomeView(), [])
  const [backToProject, setBackToProject] = useState(false)
  // Any navigation clears the way back; only "Add additional sources" sets it.
  const show = (next: HomePaneView): void => {
    setBackToProject(false)
    setView(next)
  }
  const repos = useReposByProject(home, currentProject?.id ?? null)
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
    onNewProject: () => setCreatingProject(true)
  }

  return (
    <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}>
      <Sidebar {...live} />
      <Pane {...live} />
      {creatingProject && (
        <NameModal
          title="New project"
          label="Project name"
          submitLabel="Create"
          errorText="Couldn't create the project. Check your access and try again."
          onClose={() => setCreatingProject(false)}
          onSubmit={async (name) => {
            const created = await home.actions.createProject(name)
            if (created)
              onOpenProject({ id: created.id, name: created.name, teamId: created.team_id })
            return created !== null
          }}
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
