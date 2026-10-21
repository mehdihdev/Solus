// A project's ⋯ menu on Home (SOLUSDEV-242; moved off the retired project card
// for the SOLUSDEV-317 list): Edit details · Archive · Delete (owner only,
// ADR-025, confirmed). Its clicks never reach the row, so the menu never
// selects or opens the project. A failed archive raises the shell toast.
import { useState } from 'react'
import type { Project } from '../../lib/api/resources'
import { ProjectEditModal } from '../project/ProjectEditModal'
import { DeleteConfirmModal } from './modals'
import type { HomeActions } from './useHomeData'

export interface ProjectMenuProps {
  project: Project
  canDelete: boolean
  actions: HomeActions
  onActionFailed: (body: string) => void
}

export function ProjectMenu({
  project,
  canDelete,
  actions,
  onActionFailed
}: ProjectMenuProps): React.JSX.Element {
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
            void actions
              .archiveProject(project.id)
              .then((ok) => ok)
              .catch(() => false)
              .then((ok) => {
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
        <ProjectEditModal
          initialName={project.name}
          initialDescription={project.description ?? ''}
          onClose={() => setRenaming(false)}
          onSubmit={(name, description) => actions.editProject(project.id, name, description)}
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
        <MenuItem onClick={onRename}>Edit details</MenuItem>
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
