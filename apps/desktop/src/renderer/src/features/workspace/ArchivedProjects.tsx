// The active team's archived projects (SOLUSDEV-242): hidden from the grid,
// never deleted. Collapsed by default behind a count; each row can be
// restored (member+) or permanently deleted (admin+, confirmed).
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import type { Project } from '../../lib/api/resources'
import { DeleteConfirmModal } from './modals'
import type { HomeActions } from './useHomeData'

export interface ArchivedProjectsProps {
  projects: readonly Project[]
  canManage: boolean
  canDelete: boolean
  actions: HomeActions
  onActionFailed: (body: string) => void
}

export function ArchivedProjects({
  projects,
  canManage,
  canDelete,
  actions,
  onActionFailed
}: ArchivedProjectsProps): React.JSX.Element | null {
  const [open, setOpen] = useState(false)
  if (projects.length === 0) return null
  return (
    <Card pad={0}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="interactive"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          width: '100%',
          textAlign: 'left',
          background: 'transparent',
          border: 'none',
          color: 'var(--mut)',
          cursor: 'pointer',
          fontFamily: 'var(--font-ui)',
          padding: '10px 16px'
        }}
      >
        <span style={{ display: 'inline-flex', transform: open ? 'rotate(90deg)' : undefined }}>
          <Icons.arrowR size={11} />
        </span>
        <Mono size={9}>ARCHIVED ({projects.length})</Mono>
      </button>
      {open &&
        projects.map((p) => (
          <ArchivedRow
            key={p.id}
            project={p}
            canManage={canManage}
            canDelete={canDelete}
            actions={actions}
            onActionFailed={onActionFailed}
          />
        ))}
    </Card>
  )
}

function ArchivedRow({
  project,
  canManage,
  canDelete,
  actions,
  onActionFailed
}: { project: Project } & Omit<ArchivedProjectsProps, 'projects'>): React.JSX.Element {
  const [deleting, setDeleting] = useState(false)
  return (
    <div
      style={{
        display: 'flex',
        gap: 12,
        alignItems: 'center',
        padding: '11px 16px',
        borderTop: '1px solid var(--bd)',
        opacity: 0.72
      }}
    >
      <span style={{ color: 'var(--mut)' }}>
        <Icons.graph size={15} />
      </span>
      <div style={{ flex: 1, minWidth: 0, fontSize: 12.5, fontWeight: 600 }}>{project.name}</div>
      {canManage && (
        <Button
          kind="ghost"
          size="sm"
          aria-label={`Unarchive ${project.name}`}
          onClick={() => {
            void actions.unarchiveProject(project.id).then((ok) => {
              if (!ok) onActionFailed(`Couldn't restore "${project.name}".`)
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
