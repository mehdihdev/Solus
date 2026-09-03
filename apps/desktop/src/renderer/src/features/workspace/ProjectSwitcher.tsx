// Topbar project switcher (SOLUSDEV-164). Replaces the static project name in
// the topbar with a control that shows the open project and, on click, lets the
// user jump to another of their projects or back to all projects (Home) —
// killing the "which project am I in?" confusion when several exist. The
// project list comes from useProjectSwitcher; the current project from the
// workspace store. Offline it still shows the open project's name honestly.
import { useState } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import { useWorkspaceStore, type WorkspaceProject } from '../../store/workspaceStore'
import { useProjectSwitcher } from './useProjectSwitcher'

const NO_PROJECT_LABEL = 'No project'

export interface ProjectSwitcherProps {
  onSwitch: (project: WorkspaceProject) => void
  onHome: () => void
}

export function ProjectSwitcher({ onSwitch, onHome }: ProjectSwitcherProps): React.JSX.Element {
  const current = useWorkspaceStore((s) => s.project)
  const [open, setOpen] = useState(false)

  return (
    <div style={{ position: 'relative' }}>
      <button
        type="button"
        aria-label="Switch project"
        onClick={(e) => {
          e.stopPropagation()
          setOpen((o) => !o)
        }}
        className="interactive app-no-drag"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          background: 'var(--sur)',
          border: '1px solid var(--bd)',
          color: 'var(--tx)',
          cursor: 'pointer',
          fontFamily: 'var(--font-ui)',
          fontSize: 13,
          fontWeight: 600,
          padding: '5px 12px',
          borderRadius: 6
        }}
      >
        <span style={{ color: 'var(--acc)', display: 'inline-flex' }} aria-hidden>
          <Icons.box size={12} />
        </span>
        {current?.name ?? NO_PROJECT_LABEL}
        <span style={{ color: 'var(--mut)', display: 'inline-flex' }}>
          <Chevron />
        </span>
      </button>
      {open && (
        <SwitcherDropdown
          currentId={current?.id ?? null}
          onClose={() => setOpen(false)}
          onSwitch={(p) => {
            setOpen(false)
            onSwitch(p)
          }}
          onHome={() => {
            setOpen(false)
            onHome()
          }}
        />
      )}
    </div>
  )
}

function Chevron(): React.JSX.Element {
  return (
    <svg width={11} height={11} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M6 9l6 6 6-6"
        stroke="currentColor"
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function SwitcherDropdown({
  currentId,
  onClose,
  onSwitch,
  onHome
}: {
  currentId: string | null
  onClose: () => void
  onSwitch: (project: WorkspaceProject) => void
  onHome: () => void
}): React.JSX.Element {
  const { status, groups } = useProjectSwitcher()
  const hasProjects = groups.some((g) => g.projects.length > 0)

  return (
    <>
      <div style={{ position: 'fixed', inset: 0, zIndex: 60 }} onClick={onClose} />
      <div
        role="menu"
        className="popover-in"
        onClick={(e) => e.stopPropagation()}
        style={{
          position: 'absolute',
          left: 0,
          top: '100%',
          marginTop: 6,
          zIndex: 61,
          minWidth: 240,
          maxHeight: 380,
          overflowY: 'auto',
          background: 'var(--sur)',
          border: '1px solid var(--bd)',
          borderRadius: 5,
          boxShadow: '0 14px 44px rgba(0,0,0,0.5)',
          padding: '4px 0'
        }}
      >
        <MenuRow onClick={onHome}>
          <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
            <Icons.box size={13} /> All projects
          </span>
        </MenuRow>
        <div style={{ borderTop: '1px solid var(--bd)', margin: '4px 0' }} />
        {groups.map((group) => (
          <div key={group.team.team_id}>
            <div style={{ padding: '7px 12px 4px' }}>
              <Mono size={8.5} color="var(--mut)">
                {group.team.name}
              </Mono>
            </div>
            {group.projects.map((p) => (
              <MenuRow
                key={p.id}
                active={p.id === currentId}
                onClick={() => onSwitch({ id: p.id, name: p.name })}
              >
                <span
                  style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}
                >
                  {p.name}
                </span>
                {p.id === currentId && (
                  <span style={{ color: 'var(--acc)' }}>
                    <Icons.check size={13} />
                  </span>
                )}
              </MenuRow>
            ))}
          </div>
        ))}
        {status === 'ready' && !hasProjects && (
          <div style={{ padding: '10px 12px', fontSize: 11.5, color: 'var(--mut)' }}>
            No projects yet.
          </div>
        )}
        {status === 'offline' && (
          <div style={{ padding: '10px 12px', fontSize: 11.5, color: 'var(--mut)' }}>
            Reconnect to switch between projects.
          </div>
        )}
      </div>
    </>
  )
}

/** One row of a shell dropdown menu (shared with MenuBar, SOLUSDEV-235). */
export function MenuRow({
  children,
  active = false,
  current = false,
  disabled = false,
  title,
  onClick
}: {
  children: React.ReactNode
  active?: boolean
  /** The row names where the user already is (aria-current). */
  current?: boolean
  disabled?: boolean
  title?: string
  onClick: () => void
}): React.JSX.Element {
  return (
    <button
      type="button"
      role="menuitem"
      aria-current={current || undefined}
      disabled={disabled}
      title={title}
      onClick={onClick}
      className={disabled ? undefined : 'interactive'}
      style={{
        opacity: disabled ? 0.45 : 1,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        width: '100%',
        textAlign: 'left',
        background: active ? 'color-mix(in srgb, var(--acc) 10%, transparent)' : 'transparent',
        border: 'none',
        color: active ? 'var(--acc)' : 'var(--tx)',
        cursor: disabled ? 'default' : 'pointer',
        fontFamily: 'var(--font-ui)',
        fontSize: 12.5,
        padding: '8px 12px'
      }}
    >
      {children}
    </button>
  )
}
