// Home (SOLUSDEV-242 / HOME H1): the cross-project surface. Manages ACROSS the
// active team's projects — a grid with create / open / switch / archive and
// recent activity per project — and connects WHOLE accounts (the account-scoped
// OAuth grants, SOLUSDEV-241). Everything project-specific lives in the
// workspace screens. Offline (dev bypass / unreachable API) shows an honest
// sign-in state — never a demo project (SOLUSDEV-152).
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { useWorkspaceStore, type WorkspaceProject } from '../../store/workspaceStore'
import { displayName, useMe } from './useMe'
import { useHomeData, type HomeData } from './useHomeData'
import { useOfflineReason } from './workspaceOnline'
import { useShellStore, type MainScreen } from './shellStore'
import { NameModal, JoinTeamModal } from './modals'
import { ConnectedAccountsCard } from './ConnectedAccountsCard'
import { PreferencesCard } from '../preferences/PreferencesCard'
import { ProjectGrid } from './ProjectGrid'
import { TeamSelect } from './TeamSelect'

export interface HomeScreenProps {
  onOpenProject: (project: WorkspaceProject) => void
  /** Rail navigation (the connected-accounts card jumps to the open project's Sources page). */
  onNavigate?: (screen: MainScreen) => void
}

const OFFLINE_GRID_STYLE: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0,1fr) 340px',
  gap: 16,
  marginTop: 16,
  alignItems: 'start'
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
      <div style={{ maxWidth: 1080, margin: '0 auto', padding: '26px 24px 48px' }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
          {greeting}
        </h1>
        {home.status === 'offline' ? (
          <OfflineHome />
        ) : (
          <LiveHome home={home} onOpenProject={onOpenProject} onNavigate={onNavigate} />
        )}
      </div>
    </div>
  )
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
  const currentProjectId = currentProject?.id ?? null
  const [creatingProject, setCreatingProject] = useState(false)
  const [creatingTeam, setCreatingTeam] = useState(false)
  const [joining, setJoining] = useState(false)

  return (
    <>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          marginTop: 6,
          flexWrap: 'wrap'
        }}
      >
        <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>
          {home.team ? `Projects in ${home.team.name}` : 'Your robots, one team at a time.'}
        </div>
        <TeamSelect
          teams={home.teams}
          currentId={home.team?.team_id}
          onSwitch={home.actions.switchTeam}
        />
        <div style={{ flex: 1 }} />
        <Button kind="ghost" size="sm" onClick={() => setJoining(true)}>
          <Icons.mail size={13} /> Join team
        </Button>
        <Button kind="ghost" size="sm" onClick={() => setCreatingTeam(true)}>
          <Icons.team size={13} /> New team
        </Button>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0,1fr) 340px',
          gap: 16,
          marginTop: 16,
          alignItems: 'start'
        }}
      >
        {home.team ? (
          <ProjectGrid
            team={home.team}
            projects={home.projects}
            activityByProject={home.activityByProject}
            currentProjectId={currentProjectId}
            actions={home.actions}
            onOpenProject={onOpenProject}
            onNewProject={() => setCreatingProject(true)}
            onActionFailed={toastActionFailed}
          />
        ) : (
          <Card pad={20}>
            <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>
              You&apos;re not on any teams yet. Create one, or join with an invite token.
            </div>
          </Card>
        )}
        <div style={{ display: 'grid', gap: 16 }}>
          {/* OAuth binds at ACCOUNT scope (SOLUSDEV-241): link a tool account here
              once; each project picks what it tracks on its Sources page. */}
          <ConnectedAccountsCard
            currentProject={currentProject}
            onOpenSources={onNavigate ? () => onNavigate('sources') : undefined}
          />
          {/* HOME H3 (SOLUSDEV-244): the one part of ~/.solus the user owns —
              how they engineer. Machine-local, read by SOL on every turn. */}
          <PreferencesCard />
        </div>
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
      {creatingTeam && (
        <NameModal
          title="New team"
          label="Team name"
          submitLabel="Create"
          errorText="Couldn't create the team. Please try again."
          onClose={() => setCreatingTeam(false)}
          onSubmit={(name) => home.actions.createTeam(name)}
        />
      )}
      {joining && (
        <JoinTeamModal onClose={() => setJoining(false)} onJoin={home.actions.joinTeam} />
      )}
    </>
  )
}

/** Honest offline state (dev bypass / unreachable API) — never a demo project. */
function OfflineHome(): React.JSX.Element {
  // The preferences card still works here: it is machine-local (HOME H3).
  const reason = useOfflineReason()
  return (
    <div style={OFFLINE_GRID_STYLE}>
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
