// Team screen. When the workspace is linked to the API it renders live team
// data (roster, activity, pending invites) with working invite / revoke /
// role-change / remove actions via useTeamData. When offline (dev bypass /
// unreachable API) it shows an honest sign-in state — SOLUSDEV-152 removed
// the prototype's fabricated roster and activity feed.
import { useState } from 'react'
import { Avatar } from '../../components/ui/Avatar'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { relativeTime } from '../../lib/relativeTime'
import type { Project, TeamMemberApi } from '../../lib/api/resources'
import { activityText, actorName } from './activityText'
import { useTeamData, type TeamData } from './useTeamData'
import { useOfflineReason } from '../workspace/workspaceOnline'
import { NameModal, JoinTeamModal } from '../workspace/modals'
import { MANAGER_ROLES, LiveMembers, InviteModal } from './MembersPanel'

export interface TeamScreenProps {
  /** Open a project in the Context Model (wired by the workspace shell). */
  onOpenProject?: (project: { id: string; name: string }) => void
}

/** Route between live and honest-offline rendering by connection status. */
export function TeamScreen({ onOpenProject }: TeamScreenProps = {}): React.JSX.Element {
  const data = useTeamData()
  if (data.status === 'loading') {
    return (
      <div
        style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        data-testid="team-loading"
      >
        <Spinner size={20} />
      </div>
    )
  }
  if (data.status === 'gone') return <TeamScreenGone />
  if (data.status === 'offline') return <TeamScreenOffline />
  return <TeamScreenLive data={data} onOpenProject={onOpenProject} />
}

/* ===================== GONE (answered, and it's not there) ===================== */

/**
 * The server answered: this team does not exist, or is no longer mine.
 *
 * Kept separate from the offline state because the advice is opposite. "Make
 * sure the backend is running" is actively harmful here — it points at a service
 * that is working, and a user followed it for hours. Reloading is the useful
 * action: the next load re-resolves to a team they do have.
 */
function TeamScreenGone(): React.JSX.Element {
  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 920, margin: '0 auto', padding: '22px 24px 48px' }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
          Team
        </h1>
        <Card pad={20} style={{ marginTop: 20 }}>
          <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
            That team no longer exists, or you no longer have access to it. Your API is reachable —
            nothing to restart. Reload and Solus will open a team you do belong to.
          </div>
        </Card>
      </div>
    </div>
  )
}

/* ============================ OFFLINE (honest) ============================ */

function TeamScreenOffline(): React.JSX.Element {
  const reason = useOfflineReason()
  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 920, margin: '0 auto', padding: '22px 24px 48px' }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
          Team
        </h1>
        <Card pad={20} style={{ marginTop: 20 }}>
          <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
            {reason === 'api_unreachable'
              ? "You're signed in, but Solus can't reach its API. Make sure the backend is running, then reload — members, roles, invites, and activity will appear here."
              : 'Sign in to Solus to see your team — members, roles, pending invites, and cross-domain activity all live here.'}
          </div>
        </Card>
      </div>
    </div>
  )
}

/* ============================ LIVE (API-backed) ============================ */

function TeamSwitcher({
  teams,
  currentId,
  onSwitch
}: {
  teams: TeamData['teams']
  currentId: string | undefined
  onSwitch: TeamData['actions']['switchTeam']
}): React.JSX.Element | null {
  if (teams.length < 2) return null
  return (
    <select
      aria-label="Switch team"
      value={currentId ?? ''}
      onChange={(e) => onSwitch(e.target.value)}
      style={{
        marginTop: 8,
        background: 'var(--bg)',
        color: 'var(--tx)',
        border: '1px solid var(--bd)',
        borderRadius: 3,
        padding: '5px 8px',
        fontSize: 12,
        fontFamily: 'var(--font-ui)'
      }}
    >
      {teams.map((t) => (
        <option key={t.team_id} value={t.team_id}>
          {t.name}
          {t.is_personal ? ' (personal)' : ''}
        </option>
      ))}
    </select>
  )
}

/** Which modal (if any) the team screen has open. */
type TeamModal = 'invite' | 'newTeam' | 'join' | 'newProject' | null

function TeamScreenLive({
  data,
  onOpenProject
}: {
  data: TeamData
  onOpenProject?: TeamScreenProps['onOpenProject']
}): React.JSX.Element {
  const { team, members, invites, activity, projects, teams, myRole, actions } = data
  const canManage = myRole !== null && MANAGER_ROLES.includes(myRole)
  // Project creation is member+ (viewers are read-only, API.md §2.3).
  const canCreateProject = myRole !== null && myRole !== 'viewer'
  const [modal, setModal] = useState<TeamModal>(null)
  const close = (): void => setModal(null)

  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 920, margin: '0 auto', padding: '22px 24px 48px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
              {team?.name ?? 'Team'}
            </h1>
            <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 4 }}>
              {members.length} {members.length === 1 ? 'member' : 'members'}
              {team && !team.is_personal ? '' : ' · personal workspace'}
            </div>
            <TeamSwitcher teams={teams} currentId={team?.id} onSwitch={actions.switchTeam} />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button kind="ghost" size="sm" onClick={() => setModal('join')}>
              <Icons.mail size={13} /> Join team
            </Button>
            <Button kind="ghost" size="sm" onClick={() => setModal('newTeam')}>
              <Icons.team size={13} /> New team
            </Button>
            {canManage && (
              <Button id="btn-invite" kind="primary" size="sm" onClick={() => setModal('invite')}>
                <Icons.plus size={13} /> Invite teammate
              </Button>
            )}
          </div>
        </div>

        <ProjectsPanel
          projects={projects}
          canCreate={canCreateProject}
          onOpenProject={onOpenProject}
          onNewProject={() => setModal('newProject')}
        />

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0,1fr) 380px',
            gap: 16,
            marginTop: 16,
            alignItems: 'start'
          }}
        >
          <LiveActivity activity={activity} members={members} />
          <LiveMembers
            members={members}
            invites={invites}
            myRole={myRole}
            canManage={canManage}
            onChangeRole={actions.changeRole}
            onRemove={actions.remove}
            onRevoke={actions.revoke}
          />
        </div>
      </div>
      <TeamModals modal={modal} close={close} actions={actions} onOpenProject={onOpenProject} />
    </div>
  )
}

/** The team screen's modal set, switched by the single `modal` selector. */
function TeamModals({
  modal,
  close,
  actions,
  onOpenProject
}: {
  modal: TeamModal
  close: () => void
  actions: TeamData['actions']
  onOpenProject?: TeamScreenProps['onOpenProject']
}): React.JSX.Element | null {
  if (modal === 'invite') {
    return <InviteModal onClose={close} onInvite={actions.invite} />
  }
  if (modal === 'newTeam') {
    return (
      <NameModal
        title="New team"
        label="Team name"
        errorText="Couldn't create the team. Please try again."
        onClose={close}
        onSubmit={actions.createTeam}
      />
    )
  }
  if (modal === 'join') {
    return <JoinTeamModal onClose={close} onJoin={actions.joinTeam} />
  }
  if (modal === 'newProject') {
    return (
      <NameModal
        title="New project"
        label="Project name"
        errorText="Couldn't create the project. Check your access and try again."
        onClose={close}
        onSubmit={async (name) => {
          const created = await actions.createProject(name)
          if (created && onOpenProject) onOpenProject({ id: created.id, name: created.name })
          return created !== null
        }}
      />
    )
  }
  return null
}

/** The active team's projects, with a member+ create action. */
function ProjectsPanel({
  projects,
  canCreate,
  onOpenProject,
  onNewProject
}: {
  projects: Project[]
  canCreate: boolean
  onOpenProject?: TeamScreenProps['onOpenProject']
  onNewProject: () => void
}): React.JSX.Element {
  return (
    <Card pad={0} style={{ marginTop: 20 }}>
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--bd)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}
      >
        <Mono size={9.5}>PROJECTS</Mono>
        {canCreate && (
          <Button kind="ghost" size="sm" onClick={onNewProject}>
            <Icons.plus size={12} /> New project
          </Button>
        )}
      </div>
      {projects.length === 0 ? (
        <div style={{ padding: '16px', fontSize: 12, color: 'var(--mut)' }}>
          No projects in this team yet.{canCreate ? ' Create one to start building the graph.' : ''}
        </div>
      ) : (
        projects.map((p) => (
          <div
            key={p.id}
            role="button"
            tabIndex={0}
            onClick={() => onOpenProject?.({ id: p.id, name: p.name })}
            onKeyDown={(e) => e.key === 'Enter' && onOpenProject?.({ id: p.id, name: p.name })}
            className={onOpenProject ? 'interactive' : undefined}
            style={{
              display: 'flex',
              gap: 12,
              alignItems: 'center',
              padding: '12px 16px',
              borderBottom: '1px solid var(--bd)',
              cursor: onOpenProject ? 'pointer' : 'default'
            }}
          >
            <span style={{ color: 'var(--acc)' }}>
              <Icons.graph size={15} />
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600 }}>{p.name}</div>
              {p.description && (
                <div style={{ fontSize: 11, color: 'var(--mut)' }}>{p.description}</div>
              )}
            </div>
            {onOpenProject && (
              <span style={{ color: 'var(--mut)' }}>
                <Icons.arrowR size={12} />
              </span>
            )}
          </div>
        ))
      )}
    </Card>
  )
}

function LiveActivity({
  activity,
  members
}: {
  activity: TeamData['activity']
  members: readonly TeamMemberApi[]
}): React.JSX.Element {
  return (
    <Card pad={0}>
      <div
        style={{
          padding: '13px 16px',
          borderBottom: '1px solid var(--bd)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}
      >
        <Mono size={9.5}>TEAM ACTIVITY</Mono>
        <Mono size={9}>RECENT</Mono>
      </div>
      {activity.length === 0 && (
        <div style={{ padding: '18px 16px', fontSize: 12, color: 'var(--mut)' }}>
          No activity yet. Syncs, invites, and project changes will show up here.
        </div>
      )}
      {activity.map((a) => (
        <div
          key={a.id}
          style={{
            display: 'flex',
            gap: 12,
            padding: '12px 16px',
            borderBottom: '1px solid var(--bd)'
          }}
        >
          <Avatar name={actorName(a.actor_id, members)} size={26} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>
              <strong style={{ fontWeight: 600 }}>{actorName(a.actor_id, members)}</strong>{' '}
              {activityText(a)}
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
              <span style={{ fontSize: 10, color: 'var(--mut)' }}>
                {relativeTime(a.created_at)}
              </span>
            </div>
          </div>
        </div>
      ))}
    </Card>
  )
}
