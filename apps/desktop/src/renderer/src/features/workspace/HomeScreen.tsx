// Workspace home (API.md §5 "/"): the signed-in user's projects across their
// teams, plus a recent cross-team activity feed and create-project / create-team
// actions. Offline (dev bypass / unreachable API) shows an honest sign-in
// state — SOLUSDEV-152 removed the fabricated demo project card.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { relativeTime } from '../../lib/relativeTime'
import type { Project } from '../../lib/api/resources'
import { activityText } from '../team/activityText'
import { ActivityModal, ViewAllActivityButton } from '../team/ActivityModal'
import { ACTIVITY_PREVIEW_COUNT } from '../team/activityFeed.constants'
import { displayName, useMe } from './useMe'
import { useHomeData, type HomeData } from './useHomeData'
import { useOfflineReason } from './workspaceOnline'
import { useShellStore } from './shellStore'
import { NameModal, JoinTeamModal, DeleteConfirmModal } from './modals'
import { ConnectedAccountsCard } from './ConnectedAccountsCard'

export interface HomeScreenProps {
  onOpenProject: (project: { id: string; name: string }) => void
}

/** Surface a failed background mutation (archive/unarchive) via the shell toast. */
function toastActionFailed(body: string): void {
  useShellStore.getState().setToast({ kind: 'warn', title: "That didn't work", body })
}

export function HomeScreen({ onOpenProject }: HomeScreenProps): React.JSX.Element {
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
      <div style={{ maxWidth: 980, margin: '0 auto', padding: '26px 24px 48px' }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
          {greeting}
        </h1>
        <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 4 }}>
          Your robots across every team.
        </div>
        {home.status === 'offline' ? (
          <OfflineHome />
        ) : (
          <LiveHome home={home} onOpenProject={onOpenProject} />
        )}
      </div>
    </div>
  )
}

/** Roles allowed to permanently delete a project (API.md §2.3 — admin+). */
const MANAGER_ROLES: readonly string[] = ['owner', 'admin']

function LiveHome({
  home,
  onOpenProject
}: {
  home: HomeData
  onOpenProject: HomeScreenProps['onOpenProject']
}): React.JSX.Element {
  const [creatingFor, setCreatingFor] = useState<string | null>(null)
  const [creatingTeam, setCreatingTeam] = useState(false)
  const [joining, setJoining] = useState(false)

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
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
          marginTop: 12,
          alignItems: 'start'
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {home.groups.map((group) => (
            <TeamCard
              key={group.team.team_id}
              group={group}
              actions={home.actions}
              onOpenProject={onOpenProject}
              onNewProject={() => setCreatingFor(group.team.team_id)}
            />
          ))}
          {home.groups.length === 0 && (
            <Card pad={20}>
              <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>
                You&apos;re not on any teams yet. Create one, or join with an invite token.
              </div>
            </Card>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <RecentActivity activity={home.activity} total={home.activityTotal} />
          {/* OAuth binds at ACCOUNT scope (SOLUSDEV-241): link a tool account
              here once; each project picks what it tracks on its Sources page. */}
          <ConnectedAccountsCard />
        </div>
      </div>

      <HomeModals
        actions={home.actions}
        onOpenProject={onOpenProject}
        creatingFor={creatingFor}
        creatingTeam={creatingTeam}
        joining={joining}
        closeProject={() => setCreatingFor(null)}
        closeTeam={() => setCreatingTeam(false)}
        closeJoin={() => setJoining(false)}
      />
    </>
  )
}

/** The home screen's create-project / create-team / join dialogs. */
function HomeModals({
  actions,
  onOpenProject,
  creatingFor,
  creatingTeam,
  joining,
  closeProject,
  closeTeam,
  closeJoin
}: {
  actions: HomeData['actions']
  onOpenProject: HomeScreenProps['onOpenProject']
  creatingFor: string | null
  creatingTeam: boolean
  joining: boolean
  closeProject: () => void
  closeTeam: () => void
  closeJoin: () => void
}): React.JSX.Element {
  return (
    <>
      {creatingFor && (
        <NameModal
          title="New project"
          label="Project name"
          submitLabel="Create"
          errorText="Couldn't create the project. Check your access and try again."
          onClose={closeProject}
          onSubmit={async (name) => {
            const created = await actions.createProject(creatingFor, name)
            if (created) onOpenProject({ id: created.id, name: created.name })
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
          onClose={closeTeam}
          onSubmit={(name) => actions.createTeam(name)}
        />
      )}
      {joining && <JoinTeamModal onClose={closeJoin} onJoin={actions.joinTeam} />}
    </>
  )
}

function TeamCard({
  group,
  actions,
  onOpenProject,
  onNewProject
}: {
  group: HomeData['groups'][number]
  actions: HomeData['actions']
  onOpenProject: HomeScreenProps['onOpenProject']
  onNewProject: () => void
}): React.JSX.Element {
  const role = group.team.role
  const canManage = role !== 'viewer'
  const canDelete = MANAGER_ROLES.includes(role)
  const active = group.projects.filter((p) => !p.archived_at)
  const archived = group.projects.filter((p) => p.archived_at)

  return (
    <Card pad={0}>
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--bd)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600 }}>
          {group.team.name}
          {group.team.is_personal && (
            <Mono size={8.5} color="var(--mut)" style={{ marginLeft: 8 }}>
              PERSONAL
            </Mono>
          )}
        </span>
        {canManage && (
          <Button kind="ghost" size="sm" onClick={onNewProject}>
            <Icons.plus size={12} /> New project
          </Button>
        )}
      </div>
      {active.length === 0 && archived.length === 0 ? (
        <div style={{ padding: '16px', fontSize: 12, color: 'var(--mut)' }}>
          No projects yet. Create one to start building the graph.
        </div>
      ) : (
        active.map((p) => (
          <ProjectRow
            key={p.id}
            project={p}
            onOpen={onOpenProject}
            canManage={canManage}
            canDelete={canDelete}
            actions={actions}
          />
        ))
      )}
      {archived.length > 0 && (
        <>
          <div style={{ padding: '8px 16px', borderBottom: '1px solid var(--bd)' }}>
            <Mono size={8.5} color="var(--mut)">
              ARCHIVED
            </Mono>
          </div>
          {archived.map((p) => (
            <ArchivedRow
              key={p.id}
              project={p}
              canManage={canManage}
              canDelete={canDelete}
              actions={actions}
            />
          ))}
        </>
      )}
    </Card>
  )
}

interface ProjectRowActions {
  canManage: boolean
  canDelete: boolean
  actions: HomeData['actions']
}

function ProjectRow({
  project,
  onOpen,
  canManage = false,
  canDelete = false,
  actions
}: {
  project: Project
  onOpen: HomeScreenProps['onOpenProject']
} & Partial<ProjectRowActions>): React.JSX.Element {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen({ id: project.id, name: project.name })}
      onKeyDown={(e) => e.key === 'Enter' && onOpen({ id: project.id, name: project.name })}
      className="interactive"
      style={{
        display: 'flex',
        gap: 12,
        alignItems: 'center',
        padding: '12px 16px',
        borderBottom: '1px solid var(--bd)',
        cursor: 'pointer'
      }}
    >
      <span style={{ color: 'var(--acc)' }}>
        <Icons.graph size={15} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{project.name}</div>
        {project.description && (
          <div style={{ fontSize: 11, color: 'var(--mut)' }}>{project.description}</div>
        )}
      </div>
      {canManage && actions ? (
        <ProjectMenu project={project} canDelete={canDelete} actions={actions} />
      ) : (
        <span style={{ color: 'var(--mut)' }}>
          <Icons.arrowR size={12} />
        </span>
      )}
    </div>
  )
}

function ArchivedRow({
  project,
  canManage,
  canDelete,
  actions
}: { project: Project } & ProjectRowActions): React.JSX.Element {
  const [deleting, setDeleting] = useState(false)
  return (
    <div
      style={{
        display: 'flex',
        gap: 12,
        alignItems: 'center',
        padding: '11px 16px',
        borderBottom: '1px solid var(--bd)',
        opacity: 0.62
      }}
    >
      <span style={{ color: 'var(--mut)' }}>
        <Icons.graph size={15} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{project.name}</div>
        <Mono size={8.5} color="var(--mut)">
          ARCHIVED
        </Mono>
      </div>
      {canManage && (
        <Button
          kind="ghost"
          size="sm"
          aria-label={`Unarchive ${project.name}`}
          onClick={() => {
            void actions.unarchiveProject(project.id).then((ok) => {
              if (!ok) toastActionFailed(`Couldn't restore "${project.name}".`)
            })
          }}
        >
          Unarchive
        </Button>
      )}
      {canDelete && (
        <button
          type="button"
          aria-label={`Delete ${project.name}`}
          onClick={() => setDeleting(true)}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--mut)',
            cursor: 'pointer',
            padding: 4
          }}
        >
          <Icons.x size={13} />
        </button>
      )}
      {deleting && (
        <DeleteConfirmModal
          name={project.name}
          onClose={() => setDeleting(false)}
          onConfirm={() => actions.deleteProject(project.id)}
        />
      )}
    </div>
  )
}

function ProjectMenu({
  project,
  canDelete,
  actions
}: {
  project: Project
  canDelete: boolean
  actions: HomeData['actions']
}): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [deleting, setDeleting] = useState(false)

  return (
    <div style={{ position: 'relative' }} onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        aria-label={`Project actions for ${project.name}`}
        onClick={() => setOpen((o) => !o)}
        style={{
          background: 'transparent',
          border: 'none',
          color: 'var(--mut)',
          cursor: 'pointer',
          fontSize: 16,
          lineHeight: 1,
          padding: '2px 6px'
        }}
      >
        ⋯
      </button>
      {open && (
        <MenuDropdown
          canDelete={canDelete}
          onClose={() => setOpen(false)}
          onRename={() => {
            setOpen(false)
            setRenaming(true)
          }}
          onArchive={() => {
            setOpen(false)
            void actions.archiveProject(project.id).then((ok) => {
              if (!ok) toastActionFailed(`Couldn't archive "${project.name}".`)
            })
          }}
          onDelete={() => {
            setOpen(false)
            setDeleting(true)
          }}
        />
      )}
      {renaming && (
        <NameModal
          title="Rename project"
          label="Project name"
          submitLabel="Save"
          initial={project.name}
          errorText="Couldn't rename the project. Check your access and try again."
          onClose={() => setRenaming(false)}
          onSubmit={(name) => actions.renameProject(project.id, name)}
        />
      )}
      {deleting && (
        <DeleteConfirmModal
          name={project.name}
          onClose={() => setDeleting(false)}
          onConfirm={() => actions.deleteProject(project.id)}
        />
      )}
    </div>
  )
}

function MenuDropdown({
  canDelete,
  onClose,
  onRename,
  onArchive,
  onDelete
}: {
  canDelete: boolean
  onClose: () => void
  onRename: () => void
  onArchive: () => void
  onDelete: () => void
}): React.JSX.Element {
  return (
    <>
      <div style={{ position: 'fixed', inset: 0, zIndex: 60 }} onClick={onClose} />
      <div
        role="menu"
        className="popover-in"
        style={{
          position: 'absolute',
          right: 0,
          top: '100%',
          zIndex: 61,
          minWidth: 140,
          background: 'var(--sur)',
          border: '1px solid var(--bd)',
          borderRadius: 4,
          boxShadow: '0 10px 30px rgba(0,0,0,0.4)',
          overflow: 'hidden'
        }}
      >
        <MenuItem onClick={onRename}>Rename</MenuItem>
        <MenuItem onClick={onArchive}>Archive</MenuItem>
        {canDelete && (
          <MenuItem danger onClick={onDelete}>
            Delete
          </MenuItem>
        )}
      </div>
    </>
  )
}

function MenuItem({
  children,
  danger = false,
  onClick
}: {
  children: React.ReactNode
  danger?: boolean
  onClick: () => void
}): React.JSX.Element {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="interactive"
      style={{
        display: 'block',
        width: '100%',
        textAlign: 'left',
        background: 'transparent',
        border: 'none',
        color: danger ? 'var(--err)' : 'var(--tx)',
        cursor: 'pointer',
        fontFamily: 'var(--font-ui)',
        fontSize: 12.5,
        padding: '9px 12px'
      }}
    >
      {children}
    </button>
  )
}

function RecentActivity({
  activity,
  total
}: {
  activity: HomeData['activity']
  total: number
}): React.JSX.Element {
  const [showAll, setShowAll] = useState(false)
  // The panel is a preview (SOLUSDEV-233); the dialog carries the full feed.
  const preview = activity.slice(0, ACTIVITY_PREVIEW_COUNT)
  return (
    <Card pad={0}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--bd)' }}>
        <Mono size={9.5}>RECENT ACTIVITY</Mono>
      </div>
      {activity.length === 0 ? (
        <div style={{ padding: '16px', fontSize: 12, color: 'var(--mut)' }}>Nothing yet.</div>
      ) : (
        preview.map((a) => (
          <div key={a.id} style={{ padding: '11px 16px', borderBottom: '1px solid var(--bd)' }}>
            <div style={{ fontSize: 12, lineHeight: 1.5 }}>{activityText(a)}</div>
            <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 3 }}>
              {relativeTime(a.created_at)}
            </div>
          </div>
        ))
      )}
      {total > ACTIVITY_PREVIEW_COUNT && (
        <ViewAllActivityButton total={total} onClick={() => setShowAll(true)} />
      )}
      {showAll && (
        <ActivityModal activity={activity} total={total} onClose={() => setShowAll(false)} />
      )}
    </Card>
  )
}

/** Honest offline state (dev bypass / unreachable API) — never a demo project. */
function OfflineHome(): React.JSX.Element {
  const reason = useOfflineReason()
  return (
    <Card pad={20} style={{ marginTop: 16 }}>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
        {reason === 'api_unreachable'
          ? "You're signed in, but Solus can't reach its API. Make sure the backend is running, then reload — your teams, projects, and recent activity will appear here."
          : 'Sign in to Solus to see your teams, projects, and recent activity here.'}
      </div>
    </Card>
  )
}
