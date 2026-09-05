// One project in the Home grid (SOLUSDEV-242 / HOME H1): name, description,
// the CURRENT mark when it is the open project, a preview of its own recent
// activity, and the row menu (rename / archive / delete). The card opens the
// project; when another project is open the footer reads "Switch to" so the
// user knows they are leaving one and entering another.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { relativeTime } from '../../lib/relativeTime'
import type { ActivityApi, Project } from '../../lib/api/resources'
import type { WorkspaceProject } from '../../store/workspaceStore'
import { activityText } from '../team/activityText'
import { NameModal, DeleteConfirmModal } from './modals'
import { PROJECT_CARD_ACTIVITY_COUNT } from './projectActivity'
import { ProjectActivityModal } from './ProjectActivityModal'
import type { HomeActions } from './useHomeData'

export interface ProjectCardProps {
  project: Project
  activity: readonly ActivityApi[]
  /** The open project's id, or null — drives the CURRENT mark and the footer label. */
  currentProjectId: string | null
  canManage: boolean
  canDelete: boolean
  actions: HomeActions
  onOpen: (project: WorkspaceProject) => void
  onActionFailed: (body: string) => void
}

export function ProjectCard({
  project,
  activity,
  currentProjectId,
  canManage,
  canDelete,
  actions,
  onOpen,
  onActionFailed
}: ProjectCardProps): React.JSX.Element {
  const [showActivity, setShowActivity] = useState(false)
  const isCurrent = project.id === currentProjectId
  const open = (): void => onOpen({ id: project.id, name: project.name, teamId: project.team_id })
  const footerLabel = isCurrent ? 'Open' : currentProjectId ? 'Switch to' : 'Open'

  return (
    <Card
      pad={0}
      data-testid={`project-card-${project.id}`}
      style={{
        display: 'flex',
        flexDirection: 'column',
        minWidth: 0,
        borderColor: isCurrent ? 'color-mix(in srgb, var(--acc) 55%, var(--bd))' : undefined
      }}
    >
      <div
        role="button"
        tabIndex={0}
        aria-label={`${footerLabel} ${project.name}`}
        onClick={open}
        onKeyDown={(e) => e.key === 'Enter' && open()}
        className="interactive"
        style={{ padding: '14px 16px 10px', cursor: 'pointer', flex: 1 }}
      >
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
          <span style={{ color: 'var(--acc)', marginTop: 1 }}>
            <Icons.graph size={15} />
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap'
              }}
            >
              {project.name}
            </div>
            {project.description && (
              <div style={{ fontSize: 11, color: 'var(--mut)', marginTop: 2 }}>
                {project.description}
              </div>
            )}
          </div>
          {isCurrent && (
            <Mono size={8.5} color="var(--acc)">
              CURRENT
            </Mono>
          )}
          {canManage && (
            <ProjectMenu
              project={project}
              canDelete={canDelete}
              actions={actions}
              onActionFailed={onActionFailed}
            />
          )}
        </div>
        <RecentRows activity={activity} />
      </div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '8px 12px 8px 16px',
          borderTop: '1px solid var(--bd)'
        }}
      >
        <button
          type="button"
          className="interactive"
          onClick={() => setShowActivity(true)}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            whiteSpace: 'nowrap',
            background: 'transparent',
            border: 'none',
            color: 'var(--mut)',
            cursor: 'pointer',
            fontFamily: 'var(--font-ui)',
            fontSize: 11.5,
            padding: 0
          }}
        >
          All activity <Icons.arrowR size={11} />
        </button>
        <Button kind={isCurrent ? 'ghost' : 'primary'} size="sm" onClick={open}>
          {footerLabel}
        </Button>
      </div>
      {showActivity && (
        <ProjectActivityModal
          teamId={project.team_id}
          project={project}
          onClose={() => setShowActivity(false)}
        />
      )}
    </Card>
  )
}

/** The card's activity preview — a window of the team feed, honestly labelled. */
function RecentRows({ activity }: { activity: readonly ActivityApi[] }): React.JSX.Element {
  const preview = activity.slice(0, PROJECT_CARD_ACTIVITY_COUNT)
  return (
    <div style={{ marginTop: 12 }}>
      <Mono size={8.5} color="var(--mut)">
        RECENT ACTIVITY
      </Mono>
      {preview.length === 0 ? (
        <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 4 }}>No recent activity.</div>
      ) : (
        preview.map((a) => (
          <div key={a.id} style={{ marginTop: 5, fontSize: 11.5, lineHeight: 1.4 }}>
            <span>{activityText(a)}</span>
            <span style={{ color: 'var(--mut)' }}> · {relativeTime(a.created_at)}</span>
          </div>
        ))
      )}
    </div>
  )
}

function ProjectMenu({
  project,
  canDelete,
  actions,
  onActionFailed
}: {
  project: Project
  canDelete: boolean
  actions: HomeActions
  onActionFailed: (body: string) => void
}): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [deleting, setDeleting] = useState(false)

  return (
    <div
      style={{ position: 'relative' }}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
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
          padding: '0 4px'
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
              if (!ok) onActionFailed(`Couldn't archive "${project.name}".`)
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
