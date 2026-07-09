// Workspace home (API.md §5 "/"): the signed-in user's projects across their
// teams, plus a recent cross-team activity feed and create-project / create-team
// actions. Falls back to a friendly single-project card when offline (dev
// bypass) so the demo still lands somewhere useful.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { relativeTime } from '../../lib/relativeTime'
import type { Project } from '../../lib/api/resources'
import { activityText } from '../team/activityText'
import { FALLBACK_PROJECT_NAME } from './workspaceData.constants'
import { displayName, useMe } from './useMe'
import { useHomeData, type HomeData } from './useHomeData'
import { useShellStore } from './shellStore'

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
          <OfflineHome onOpenProject={onOpenProject} />
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

        <RecentActivity activity={home.activity} />
      </div>

      {creatingFor && (
        <NameModal
          title="New project"
          label="Project name"
          submitLabel="Create"
          errorText="Couldn't create the project. Check your access and try again."
          onClose={() => setCreatingFor(null)}
          onSubmit={async (name) => {
            const created = await home.actions.createProject(creatingFor, name)
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

function RecentActivity({ activity }: { activity: HomeData['activity'] }): React.JSX.Element {
  return (
    <Card pad={0}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--bd)' }}>
        <Mono size={9.5}>RECENT ACTIVITY</Mono>
      </div>
      {activity.length === 0 ? (
        <div style={{ padding: '16px', fontSize: 12, color: 'var(--mut)' }}>Nothing yet.</div>
      ) : (
        activity.map((a) => (
          <div key={a.id} style={{ padding: '11px 16px', borderBottom: '1px solid var(--bd)' }}>
            <div style={{ fontSize: 12, lineHeight: 1.5 }}>{activityText(a)}</div>
            <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 3 }}>
              {relativeTime(a.created_at)}
            </div>
          </div>
        ))
      )}
    </Card>
  )
}

function OfflineHome({
  onOpenProject
}: {
  onOpenProject: HomeScreenProps['onOpenProject']
}): React.JSX.Element {
  return (
    <Card pad={0} style={{ marginTop: 16 }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--bd)' }}>
        <Mono size={9.5}>YOUR PROJECT</Mono>
      </div>
      <ProjectRow
        project={{
          id: 'demo',
          name: FALLBACK_PROJECT_NAME,
          team_id: 'demo',
          description: 'Six-wheel autonomous rover',
          archived_at: null,
          created_at: '',
          updated_at: ''
        }}
        onOpen={onOpenProject}
      />
      <div style={{ padding: '12px 16px', fontSize: 11, color: 'var(--mut)', lineHeight: 1.5 }}>
        Connect the workspace to your account to see every team and project here.
      </div>
    </Card>
  )
}

/** Shared modal chrome: dim backdrop, centered card, click-out to close. */
function ModalShell({
  onClose,
  children
}: {
  onClose: () => void
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.55)',
        zIndex: 70,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }}
      onClick={onClose}
    >
      <div onClick={(e) => e.stopPropagation()}>
        <Card pad={24} style={{ width: 360, boxShadow: '0 18px 60px rgba(0,0,0,0.5)' }}>
          {children}
        </Card>
      </div>
    </div>
  )
}

const MODAL_INPUT_STYLE: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  marginTop: 16,
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '10px 12px',
  fontSize: 13,
  fontFamily: 'var(--font-ui)',
  outline: 'none'
}

function NameModal({
  title,
  label,
  submitLabel = 'Create',
  initial = '',
  errorText = 'Something went wrong. Please try again.',
  onClose,
  onSubmit
}: {
  title: string
  label: string
  submitLabel?: string
  initial?: string
  errorText?: string
  onClose: () => void
  /** Resolve true on success (modal closes) or false to keep it open with an error. */
  onSubmit: (name: string) => Promise<boolean>
}): React.JSX.Element {
  const [name, setName] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const submit = async (): Promise<void> => {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    const ok = await onSubmit(name.trim())
    if (ok) {
      onClose()
      return
    }
    setBusy(false)
    setError(errorText)
  }
  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>{title}</div>
      <input
        aria-label={label}
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder={label}
        autoFocus
        onKeyDown={(e) => e.key === 'Enter' && void submit()}
        style={MODAL_INPUT_STYLE}
      />
      {error && <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="primary" size="sm" onClick={() => void submit()}>
          {busy ? <Spinner size={11} color="var(--acc-ink)" /> : submitLabel}
        </Button>
      </div>
    </ModalShell>
  )
}

function JoinTeamModal({
  onClose,
  onJoin
}: {
  onClose: () => void
  onJoin: HomeData['actions']['joinTeam']
}): React.JSX.Element {
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (): Promise<void> => {
    if (!token.trim()) return
    setBusy(true)
    setError(null)
    const joined = await onJoin(token.trim())
    setBusy(false)
    if (!joined) {
      setError("Couldn't join with that token. It may be invalid, expired, or for another email.")
      return
    }
    onClose()
  }

  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Join a team</div>
      <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 4, lineHeight: 1.5 }}>
        Paste the one-time invite token a teammate shared with you.
      </div>
      <input
        aria-label="Invite token"
        value={token}
        onChange={(e) => setToken(e.target.value)}
        placeholder="invite token"
        autoFocus
        onKeyDown={(e) => e.key === 'Enter' && void submit()}
        style={{ ...MODAL_INPUT_STYLE, fontFamily: 'var(--font-mono)' }}
      />
      {error && <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="primary" size="sm" onClick={() => void submit()}>
          {busy ? <Spinner size={11} color="var(--acc-ink)" /> : 'Join'}
        </Button>
      </div>
    </ModalShell>
  )
}

function DeleteConfirmModal({
  name,
  onClose,
  onConfirm
}: {
  name: string
  onClose: () => void
  /** Resolve true on success (modal closes) or false to keep it open with an error. */
  onConfirm: () => Promise<boolean>
}): React.JSX.Element {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const confirm = async (): Promise<void> => {
    setBusy(true)
    setError(null)
    const ok = await onConfirm()
    if (ok) {
      onClose()
      return
    }
    setBusy(false)
    setError("Couldn't delete this project. Check your access and try again.")
  }
  return (
    <ModalShell onClose={onClose}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Delete project</div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 }}>
        Permanently delete <strong style={{ color: 'var(--tx)' }}>{name}</strong> and its graph.
        This cannot be undone.
      </div>
      {error && <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' }}>
        <Button kind="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button kind="danger" size="sm" onClick={() => void confirm()}>
          {busy ? <Spinner size={11} /> : 'Delete project'}
        </Button>
      </div>
    </ModalShell>
  )
}
