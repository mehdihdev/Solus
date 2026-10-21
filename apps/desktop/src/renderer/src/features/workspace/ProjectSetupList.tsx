// Home's PROJECT SETUP card (SOLUSDEV-317, concept 1): what the current
// project is made of, as one list — ON THIS COMPUTER (the linked folder),
// SOURCES (each tool, its items, its next step) and .SOLUS (what SOL knows).
// Each part is its own component with its own rules; this only frames them.
import type { WorkspaceProject } from '../../store/workspaceStore'
import { Mono } from '../../components/ui/Mono'
import { ProjectFolderCard } from '../project/ProjectFolderCard'
import { ProjectSourcesSummary } from './ProjectSourcesSummary'
import { SolusSummaryRow } from './SolusSummaryRow'

export interface ProjectSetupListProps {
  project: WorkspaceProject
  /** Opens Connected accounts for tools not linked yet. */
  onAddSources: () => void
  /** Opens the .solus tab, where instructions are written. */
  onAddInstructions: () => void
}

export function ProjectSetupList({
  project,
  onAddSources,
  onAddInstructions
}: ProjectSetupListProps): React.JSX.Element {
  return (
    <section
      data-testid="project-setup"
      aria-label="Project setup"
      style={{ background: 'var(--sur)', border: '1px solid var(--bd)', borderRadius: 4 }}
    >
      <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--bd)' }}>
        <Mono size={10} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
          PROJECT SETUP
        </Mono>
      </div>
      <Part label="ON THIS COMPUTER">
        <ProjectFolderCard key={project.id} projectId={project.id} compact bare />
      </Part>
      <Part>
        <ProjectSourcesSummary project={project} onAdd={onAddSources} />
      </Part>
      <Part label=".SOLUS — WHAT SOL KNOWS" last>
        <div style={{ padding: '4px 0 6px' }}>
          <SolusSummaryRow projectId={project.id} onAddInstructions={onAddInstructions} />
        </div>
      </Part>
    </section>
  )
}

function Part({
  label,
  last = false,
  children
}: {
  label?: string
  last?: boolean
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <div style={{ padding: '12px 16px 8px', borderBottom: last ? 'none' : '1px solid var(--bd)' }}>
      {label && (
        <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
          {label}
        </Mono>
      )}
      {children}
    </div>
  )
}
