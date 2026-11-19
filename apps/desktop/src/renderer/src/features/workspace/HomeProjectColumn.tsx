// SOLUSDEV-328 (A2, docs/wireflows/home.md "Fills the window"): on a wide Home the CURRENT project
// sits in its own column beside the team overview instead of replacing it. No tabs: its header
// (Live Bench, Open workspace), Sources and .solus side by side, then the project's own activity
// (server-filtered, paged) filling the height. With no current project in this team, a plain prompt.
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import type { WorkspaceProject } from '../../store/workspaceStore'
import { ProjectActivityFeed } from './ProjectActivityFeed'
import { ProjectSourcesSummary } from './ProjectSourcesSummary'
import { RepoLine } from './RepoLine'
import { SolusSummaryRow } from './SolusSummaryRow'
import type { LinkedRepo } from './useProjectRepos'

export interface HomeProjectColumnProps {
  /** The current project when it belongs to the team on show, else null. */
  project: WorkspaceProject | null
  description: string | null
  repos: readonly LinkedRepo[]
  onOpen: () => void
  onBench: () => void
  onManageSources: () => void
  /** .solus notes are written on the project pane's .solus tab. */
  onAddInstructions: () => void
}

export function HomeProjectColumn(props: HomeProjectColumnProps): React.JSX.Element {
  const { project } = props
  if (!project)
    return (
      <div style={{ padding: 24, fontSize: 12.5, color: 'var(--mut)' }}>
        Pick a project to see it here.
      </div>
    )
  return (
    <section
      aria-label={project.name}
      style={{ display: 'grid', gap: 16, padding: '16px 20px 24px' }}
    >
      <Header {...props} project={project} />
      <div style={TWO_UP}>
        <Card pad={16} style={{ minWidth: 0 }}>
          <ProjectSourcesSummary project={project} onAdd={props.onManageSources} />
        </Card>
        <Card pad={16} style={{ minWidth: 0 }}>
          <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
            .SOLUS
          </Mono>
          <div style={{ marginTop: 8 }}>
            <SolusSummaryRow projectId={project.id} onAddInstructions={props.onAddInstructions} />
          </div>
        </Card>
      </div>
      {project.teamId ? (
        <ProjectActivityFeed project={{ id: project.id, teamId: project.teamId }} />
      ) : (
        <Card pad={16}>
          <div style={{ fontSize: 12, color: 'var(--mut)' }}>
            This project&apos;s team isn&apos;t known yet — reopen it from the list.
          </div>
        </Card>
      )}
    </section>
  )
}

function Header({
  project,
  description,
  repos,
  onOpen,
  onBench
}: HomeProjectColumnProps & { project: WorkspaceProject }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 10 }}>
      <div style={{ flex: '1 1 220px', minWidth: 0 }}>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>{project.name}</h3>
        {repos.length > 0 && (
          <div style={{ marginTop: 4 }}>
            <RepoLine repos={repos} linked />
          </div>
        )}
        {description && (
          <div style={{ marginTop: 2, fontSize: 12, color: 'var(--mut)' }}>{description}</div>
        )}
      </div>
      <Button kind="ghost" size="sm" onClick={onBench}>
        Live Bench
      </Button>
      <Button kind="primary" size="sm" onClick={onOpen}>
        Open workspace
      </Button>
    </div>
  )
}

const TWO_UP: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
  gap: 12,
  alignItems: 'start'
}
