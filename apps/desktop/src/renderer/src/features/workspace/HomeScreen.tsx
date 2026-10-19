// Home (SOLUSDEV-242 / HOME H1 → H5; SOLUSDEV-317 layout, concept B): the
// cross-project AND cross-team surface. The active team is always visible
// (the strip), with the switcher only when the user belongs to more than one
// team. Beneath it, two columns: the team's projects as a list (selecting one
// makes it current) with the ACCOUNT nav, and ONE pane showing the current
// project (folder, sources, activity, .solus), the members view (roster,
// invites, GitHub org, team feed) or connected accounts. Offline (dev bypass /
// unreachable API) shows an honest sign-in state — never a demo project
// (SOLUSDEV-152); a team that is gone says so — never "restart the backend".
import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { useWorkspaceStore, type WorkspaceProject } from '../../store/workspaceStore'
import type { Project } from '../../lib/api/resources'
import { personalTeam } from '../../lib/api/resources'
import { MANAGER_ROLES, LiveMembers } from '../team/MembersPanel'
import { displayName, useMe } from './useMe'
import { useHomeData, type HomeData } from './useHomeData'
import { useHomeTeam, type HomeTeam } from './useHomeTeam'
import { switchWorkspaceProject } from './projectSwitch'
import { useOfflineReason } from './workspaceOnline'
import { useShellStore, type MainScreen } from './shellStore'
import { NameModal } from './modals'
import { ConnectedAccountsCard } from './ConnectedAccountsCard'
import { GitHubOrgCard } from './GitHubOrgCard'
import { HomeAccountNav, type AccountsPosition, type HomePaneView } from './HomeAccountNav'
import { useAccountConnections } from './useAccountConnections'
import { HomeProjectList } from './HomeProjectList'
import { HomeProjectPane } from './HomeProjectPane'
import { HomeTeamModals, type HomeTeamModal } from './HomeTeamModals'
import { TeamActivityPanel } from './TeamActivityPanel'
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
  onNewProject: () => void
}

function Sidebar(props: LiveProps): React.JSX.Element {
  const { home, team, currentProject, view, onShow, openModal, onNewProject } = props
  const accounts = useAccountsPosition(view)
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
      <div style={{ maxWidth: PANE_MAX_WIDTH, padding: '26px 32px 48px' }}>
        {props.view === 'members' && <MembersView {...props} />}
        {props.view === 'accounts' && (
          // OAuth binds at ACCOUNT scope (SOLUSDEV-241): link a tool account here
          // once; each project picks what it tracks from the same card.
          <ConnectedAccountsCard
            currentProject={props.currentProject}
            onNavigate={props.onNavigate}
          />
        )}
        {props.view === 'project' && <ProjectView {...props} />}
      </div>
    </main>
  )
}

function ProjectView({
  home,
  currentProject,
  onShow,
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
      onOpen={() => onOpenProject(currentProject)}
      onBench={() => onNavigate?.('bench')}
      onManageSources={() => onShow('accounts')}
    />
  )
}

function MembersView({ home, team, onNavigate, openModal }: LiveProps): React.JSX.Element {
  const canManage = team.myRole !== null && MANAGER_ROLES.includes(team.myRole)
  if (home.team === null || team.status !== 'ready')
    return (
      <Card pad={20}>
        <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>Loading the team…</div>
      </Card>
    )
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <LiveMembers
        members={team.members}
        invites={team.invites}
        myRole={team.myRole}
        canManage={canManage}
        onChangeRole={team.actions.changeRole}
        onRemove={team.actions.remove}
        onRevoke={team.actions.revoke}
        onInvite={() => openModal('invite')}
      />
      <GitHubSlot home={home} team={team} canManage={canManage} onNavigate={onNavigate} />
      <TeamActivityPanel
        activity={team.activity}
        members={team.members}
        total={team.activityTotal}
        hasMore={team.activityHasMore}
        onLoadMore={team.actions.loadMoreActivity}
      />
    </div>
  )
}

/** ADR-039: a GitHub organization belongs to a COLLABORATIVE team only. */
function GitHubSlot({
  home,
  team,
  canManage,
  onNavigate
}: Pick<LiveProps, 'home' | 'team' | 'onNavigate'> & {
  canManage: boolean
}): React.JSX.Element | null {
  const active = home.team
  if (!active || active.is_personal || team.status !== 'ready') return null
  return (
    <GitHubOrgCard
      key={active.team_id}
      teamId={active.team_id}
      canManage={canManage}
      onUpgrade={onNavigate ? () => onNavigate('billing') : undefined}
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
  const [view, setView] = useState<HomePaneView>('project')
  const onUpgrade = onNavigate ? () => onNavigate('billing') : undefined
  const live: LiveProps = {
    home,
    greeting,
    team,
    currentProject,
    view,
    onShow: setView,
    onOpenProject,
    onNavigate,
    openModal: setModal,
    onUpgrade,
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
