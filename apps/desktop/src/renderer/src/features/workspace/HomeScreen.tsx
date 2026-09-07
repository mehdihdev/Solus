// Home (SOLUSDEV-242 / HOME H1 → H5): the cross-project AND cross-team surface.
// The active team is always visible (the strip), with the switcher only when
// the user belongs to more than one team; its projects as a grid; its members
// with roles, one-time invites, join-by-token; the humanised team feed; and
// the account-level cards (connected accounts, how you engineer). Everything
// project-specific lives in the workspace screens. Offline (dev bypass /
// unreachable API) shows an honest sign-in state — never a demo project
// (SOLUSDEV-152); a team that is gone says so — never "restart the backend".
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { useWorkspaceStore, type WorkspaceProject } from '../../store/workspaceStore'
import { personalTeam } from '../../lib/api/resources'
import { MANAGER_ROLES, LiveMembers } from '../team/MembersPanel'
import { PreferencesCard } from '../preferences/PreferencesCard'
import { ProjectFolderCard } from '../project/ProjectFolderCard'
import { displayName, useMe } from './useMe'
import { useHomeData, type HomeData } from './useHomeData'
import { useHomeTeam, type HomeTeam } from './useHomeTeam'
import { switchWorkspaceProject } from './projectSwitch'
import { useOfflineReason } from './workspaceOnline'
import { useShellStore, type MainScreen } from './shellStore'
import { NameModal } from './modals'
import { ConnectedAccountsCard } from './ConnectedAccountsCard'
import { HomeTeamModals, type HomeTeamModal } from './HomeTeamModals'
import { ProjectGrid } from './ProjectGrid'
import { TeamActivityPanel } from './TeamActivityPanel'
import { TeamStrip } from './TeamStrip'

export interface HomeScreenProps {
  onOpenProject: (project: WorkspaceProject) => void
  /** Rail navigation (Sources from the accounts card; Billing from a plan limit). */
  onNavigate?: (screen: MainScreen) => void
}

/** Home fills the window up to this width — wide enough for four project cards
 *  beside the side column on a large display, without unused margins on either
 *  side at the default window size. */
const HOME_MAX_WIDTH = 1480

const GRID_STYLE: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0,1fr) 420px',
  gap: 16,
  marginTop: 16,
  alignItems: 'start'
}

/** "Switch to" on a card re-scopes Home to that project and stays here — the
 *  same choke point as every other switch (SOLUSDEV-242), no navigation. */
function switchHomeProject(project: WorkspaceProject): void {
  switchWorkspaceProject(project, 'home')
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

  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: HOME_MAX_WIDTH, margin: '0 auto', padding: '26px 24px 48px' }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
          {greeting}
        </h1>
        {home.status === 'offline' && <OfflineHome />}
        {home.status === 'gone' && <GoneHome home={home} />}
        {home.status === 'ready' && (
          <LiveHome home={home} onOpenProject={onOpenProject} onNavigate={onNavigate} />
        )}
      </div>
    </div>
  )
}

interface LiveProps {
  home: HomeData
  team: HomeTeam
  currentProject: WorkspaceProject | null
  onOpenProject: HomeScreenProps['onOpenProject']
  onNavigate: HomeScreenProps['onNavigate']
  openModal: (modal: HomeTeamModal) => void
  onNewProject: () => void
}

function ProjectsColumn({
  home,
  team,
  currentProject,
  onOpenProject,
  onNewProject
}: LiveProps): React.JSX.Element {
  const teamReady = home.team !== null && team.status === 'ready'
  return (
    <div style={{ display: 'grid', gap: 16, minWidth: 0 }}>
      {home.team ? (
        <ProjectGrid
          team={home.team}
          projects={home.projects}
          activityByProject={home.activityByProject}
          currentProjectId={currentProject?.id ?? null}
          actions={home.actions}
          onOpenProject={onOpenProject}
          onSwitchProject={switchHomeProject}
          onNewProject={onNewProject}
          onActionFailed={toastActionFailed}
        />
      ) : (
        <Card pad={20}>
          <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>
            You&apos;re not on any teams yet. Create one, or join with an invite token.
          </div>
        </Card>
      )}
      {teamReady && (
        <TeamActivityPanel
          activity={team.activity}
          members={team.members}
          total={team.activityTotal}
          hasMore={team.activityHasMore}
          onLoadMore={team.actions.loadMoreActivity}
        />
      )}
    </div>
  )
}

function SideColumn({ home, team, currentProject, openModal }: LiveProps): React.JSX.Element {
  const teamReady = home.team !== null && team.status === 'ready'
  const canManage = team.myRole !== null && MANAGER_ROLES.includes(team.myRole)
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      {teamReady && (
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
      )}
      {/* The current project's working copy on THIS machine (moved here from the
          Project Overview): machine-local, re-scoped by "Switch to" on a card. */}
      <LocalFolderSection currentProject={currentProject} />
      {/* OAuth binds at ACCOUNT scope (SOLUSDEV-241): link a tool account here
          once; each project picks what it tracks on its Sources page. */}
      <ConnectedAccountsCard currentProject={currentProject} />
      {/* HOME H3 (SOLUSDEV-244): the one part of ~/.solus the user owns —
          how they engineer. Machine-local, read by SOL on every turn. */}
      <PreferencesCard />
    </div>
  )
}

function LocalFolderSection({
  currentProject
}: {
  currentProject: WorkspaceProject | null
}): React.JSX.Element {
  return (
    // A grid item defaults to min-width:auto; without this the card's rows
    // could widen the fixed right column and give the page a horizontal scroll.
    <div style={{ minWidth: 0 }}>
      <div style={{ margin: '0 0 10px' }}>
        <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
          LOCAL FOLDER
        </Mono>
      </div>
      {currentProject ? (
        <ProjectFolderCard key={currentProject.id} projectId={currentProject.id} />
      ) : (
        <Card pad={16}>
          <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
            Open or switch to a project to link a working copy on this computer.
          </div>
        </Card>
      )}
    </div>
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
  onOpenProject,
  onNavigate
}: {
  home: HomeData
  onOpenProject: HomeScreenProps['onOpenProject']
  onNavigate: HomeScreenProps['onNavigate']
}): React.JSX.Element {
  const currentProject = useWorkspaceStore((s) => s.project)
  const team = useHomeTeam(home.team, home.me, home.actions.refresh)
  const [creatingProject, setCreatingProject] = useState(false)
  const [modal, setModal] = useState<HomeTeamModal>(null)
  const onUpgrade = onNavigate ? () => onNavigate('billing') : undefined
  const live: LiveProps = {
    home,
    team,
    currentProject,
    onOpenProject,
    onNavigate,
    openModal: setModal,
    onNewProject: () => setCreatingProject(true)
  }

  return (
    <>
      <TeamStrip
        team={home.team}
        teams={home.teams}
        memberCount={memberCount(team)}
        myRole={team.myRole}
        teamLimit={team.teamLimit}
        onSwitch={home.actions.switchTeam}
        onJoin={() => setModal('join')}
        onNewTeam={() => setModal('newTeam')}
        onInvite={() => setModal('invite')}
        onRename={() => setModal('rename')}
        onLeave={() => setModal('leave')}
        onDelete={() => setModal('delete')}
        onUpgrade={onUpgrade}
      />
      <div style={GRID_STYLE}>
        <ProjectsColumn {...live} />
        <SideColumn {...live} />
      </div>
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
    </>
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
  // The preferences card still works here: it is machine-local (HOME H3).
  const reason = useOfflineReason()
  return (
    <div style={GRID_STYLE}>
      <Card pad={20}>
        <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
          {reason === 'api_unreachable'
            ? "You're signed in, but Solus can't reach its API. Make sure the backend is running, then reload — your teams, projects, and recent activity will appear here."
            : 'Sign in to Solus to see your teams, projects, and recent activity here.'}
        </div>
      </Card>
      <PreferencesCard />
    </div>
  )
}
