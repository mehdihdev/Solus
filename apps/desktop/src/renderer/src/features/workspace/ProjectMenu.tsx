// A project's ⋯ menu on Home (SOLUSDEV-242; moved off the retired project card
// for the SOLUSDEV-317 list): Edit details · Archive · Delete (owner only,
// ADR-025, confirmed). Its clicks never reach the row, so the menu never
// selects or opens the project. A failed archive raises the shell toast.
// The dropdown is portalled to document.body at a fixed position: the projects
// table scrolls sideways (overflow-x: auto), which clips anything absolutely
// positioned inside it — the menu was cut off under the last rows.
import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'
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
  const { anchor, triggerRef, open, setOpen } = useMenuAnchor()
  const [renaming, setRenaming] = useState(false)
  const [deleting, setDeleting] = useState(false)

  return (
    <div
      style={{ position: 'relative' }}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Project actions for ${project.name}`}
        onClick={() => setOpen(!open)}
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
      {anchor && (
        <MenuDropdown
          place={anchor}
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

/** The open menu's fixed placement, measured from its ⋯ trigger when it opens. */
function useMenuAnchor(): {
  anchor: MenuPlacement | null
  triggerRef: React.RefObject<HTMLButtonElement | null>
  open: boolean
  setOpen: (next: boolean) => void
} {
  const [anchor, setAnchor] = useState<MenuPlacement | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const setOpen = (next: boolean): void => {
    const rect = triggerRef.current?.getBoundingClientRect()
    setAnchor(next && rect ? menuPlacement(rect, window.innerHeight) : null)
  }
  return { anchor, triggerRef, open: anchor !== null, setOpen }
}

/** Rough height of the open menu (three items), for the flip-above decision. */
const MENU_HEIGHT = 120
const MENU_GAP = 4
const VIEWPORT_MARGIN = 8

export type MenuPlacement = { right: number } & ({ top: number } | { bottom: number })

/** Right-aligned under the ⋯, or above it when the window has no room below. */
export function menuPlacement(
  rect: Pick<DOMRect, 'top' | 'bottom' | 'right'>,
  viewportHeight: number,
  viewportWidth: number = window.innerWidth
): MenuPlacement {
  const right = Math.max(VIEWPORT_MARGIN, viewportWidth - rect.right)
  const fitsBelow = rect.bottom + MENU_GAP + MENU_HEIGHT <= viewportHeight - VIEWPORT_MARGIN
  return fitsBelow
    ? { right, top: rect.bottom + MENU_GAP }
    : { right, bottom: viewportHeight - rect.top + MENU_GAP }
}

function MenuDropdown({
  place,
  canDelete,
  onClose,
  onRename,
  onArchive,
  onDelete
}: {
  place: MenuPlacement
  canDelete: boolean
  onClose: () => void
  onRename: () => void
  onArchive: () => void
  onDelete: () => void
}): React.JSX.Element {
  return createPortal(
    // Clicks inside the portal still bubble through React to the row: stop them here.
    <div onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
      <div style={{ position: 'fixed', inset: 0, zIndex: 60 }} onClick={onClose} />
      <div
        role="menu"
        className="popover-in"
        style={{
          position: 'fixed',
          ...place,
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
    </div>,
    document.body
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
