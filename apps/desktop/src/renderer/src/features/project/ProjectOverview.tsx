// Project hub / overview screen (SOLUSDEV-164). The landing surface when a
// project is opened: it orients the user in THIS project — name, description,
// real entity/relation/source counts — and offers clear jumps into each domain
// (Context Model, Live Bench, SOL) and into source management, instead of
// dropping them straight onto the Context Model canvas. Counts and sources come
// from useProjectOverview; empty/offline states are honest (SOLUSDEV-152).
import { useState } from 'react'
import type { MainScreen } from '../workspace/shellStore'
import { updateProject, type Source } from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { Card } from '../../components/ui/Card'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'
import { useOfflineReason } from '../workspace/workspaceOnline'
import { ProjectEditModal } from './ProjectEditModal'
import { ProjectFolderCard } from './ProjectFolderCard'
import { sourceStatusColor, sourceTypeLabel } from './sourcePresentation'
import { useProjectOverview } from './useProjectOverview'

/** Derive a clone URL from a connected GitHub source, if any (config.repo is
 *  the `owner/name` full name recorded by the connector). Best-effort prefill. */
function githubRepoUrl(sources: Source[]): string | undefined {
  const gh = sources.find((s) => s.type === 'github')
  const repo = gh?.config?.repo
  return typeof repo === 'string' && repo ? `https://github.com/${repo}.git` : undefined
}

export interface ProjectOverviewProps {
  onNavigate: (screen: MainScreen) => void
}

interface Domain {
  screen: MainScreen
  title: string
  body: string
  icon: React.ReactNode
}

const DOMAINS: readonly Domain[] = [
  {
    screen: 'graph',
    title: 'Context Model',
    body: 'The unified graph across code, electronics, CAD, and runtime.',
    icon: <Icons.graph size={17} />
  },
  {
    screen: 'bench',
    title: 'Live Bench',
    body: 'Simulate from CAD or stream live telemetry from the robot.',
    icon: <Icons.bench size={17} />
  },
  {
    screen: 'sol',
    title: 'SOL',
    body: 'Ask the agent to diagnose cross-domain problems and propose fixes.',
    icon: <Icons.sol size={17} />
  }
]

export function ProjectOverview({ onNavigate }: ProjectOverviewProps): React.JSX.Element {
  const overview = useProjectOverview()
  const reason = useOfflineReason()

  if (overview.status === 'loading') {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spinner size={20} />
      </div>
    )
  }

  if (overview.status === 'offline' && !overview.name) {
    return (
      <ScreenEmptyState
        icon={<Icons.box size={30} />}
        title="Select a project"
        body="Open a project from Home to see its overview and jump into its domains."
      />
    )
  }

  const sources = overview.sources

  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '26px 24px 48px' }}>
        <ProjectHeader
          id={overview.id}
          name={overview.name}
          description={overview.description}
          onSaved={overview.refresh}
        />

        {overview.status === 'offline' ? (
          <Card pad={16} style={{ marginTop: 18 }}>
            <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
              {reason === 'api_unreachable'
                ? "Solus can't reach its API right now — this project's live counts and sources will appear once the backend is reachable."
                : 'Sign in to see this project’s live counts and connected sources.'}
            </div>
          </Card>
        ) : (
          <div style={{ display: 'flex', gap: 12, marginTop: 18 }}>
            <StatTile value={overview.entityCount} label="ENTITIES" />
            <StatTile value={overview.relationCount} label="RELATIONS" />
            <StatTile value={sources.length} label="SOURCES" />
          </div>
        )}

        <SectionLabel>DOMAINS</SectionLabel>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          {DOMAINS.map((d) => (
            <DomainCard key={d.screen} domain={d} onClick={() => onNavigate(d.screen)} />
          ))}
        </div>

        {overview.id && (
          <>
            <SectionLabel>LOCAL FOLDER</SectionLabel>
            <ProjectFolderCard projectId={overview.id} suggestedRepoUrl={githubRepoUrl(sources)} />
          </>
        )}

        <SectionLabel>SOURCES</SectionLabel>
        <SourcesSummary
          sources={sources}
          offline={overview.status === 'offline'}
          onNavigate={onNavigate}
        />
      </div>
    </div>
  )
}

/** Editable project header: name + description with an inline Edit action. */
function ProjectHeader({
  id,
  name,
  description,
  onSaved
}: {
  id: string | null
  name: string
  description: string | null
  onSaved: () => Promise<void>
}): React.JSX.Element {
  const [editing, setEditing] = useState(false)

  const save = async (nextName: string, nextDescription: string): Promise<boolean> => {
    if (!id) return false
    try {
      await updateProject(id, { name: nextName, description: nextDescription })
      // Keep the topbar/switcher label in step with the rename.
      useWorkspaceStore.getState().setProject({ id, name: nextName })
      await onSaved()
      return true
    } catch {
      return false
    }
  }

  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
          {name}
        </h1>
        <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 4 }}>
          {description || 'No description yet.'}
        </div>
      </div>
      {id && (
        <Button kind="ghost" size="sm" onClick={() => setEditing(true)}>
          Edit
        </Button>
      )}
      {editing && (
        <ProjectEditModal
          initialName={name}
          initialDescription={description ?? ''}
          onClose={() => setEditing(false)}
          onSubmit={save}
        />
      )}
    </div>
  )
}

function SourcesSummary({
  sources,
  offline,
  onNavigate
}: {
  sources: Source[]
  offline: boolean
  onNavigate: (screen: MainScreen) => void
}): React.JSX.Element {
  if (!offline && sources.length === 0) {
    return (
      <Card pad={20}>
        <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55, marginBottom: 14 }}>
          No tools connected yet. Connect GitHub, KiCad, or another tool to start building this
          robot&apos;s graph.
        </div>
        <Button kind="primary" size="sm" onClick={() => onNavigate('sources')}>
          <Icons.plus size={13} /> Connect a tool
        </Button>
      </Card>
    )
  }
  return (
    <Card pad={0}>
      {sources.map((s, i) => (
        <div
          key={s.id}
          style={{
            display: 'flex',
            gap: 10,
            alignItems: 'center',
            padding: '11px 16px',
            borderBottom: i < sources.length - 1 ? '1px solid var(--bd)' : 'none'
          }}
        >
          <span
            aria-hidden
            style={{
              width: 7,
              height: 7,
              borderRadius: 99,
              background: sourceStatusColor(s.status),
              flexShrink: 0
            }}
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>{s.name}</div>
            <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>{sourceTypeLabel(s.type)}</div>
          </div>
          <Mono size={8.5} color="var(--mut)">
            {s.status.toUpperCase()}
          </Mono>
        </div>
      ))}
      {offline && (
        <div style={{ padding: '14px 16px', fontSize: 12, color: 'var(--mut)' }}>
          Connected tools will list here once Solus can reach its API.
        </div>
      )}
      <div style={{ padding: '12px 16px', borderTop: '1px solid var(--bd)' }}>
        <Button kind="ghost" size="sm" onClick={() => onNavigate('sources')}>
          <Icons.link size={13} /> Manage sources
        </Button>
      </div>
    </Card>
  )
}

function StatTile({ value, label }: { value: number; label: string }): React.JSX.Element {
  return (
    <Card pad={16} style={{ flex: 1, textAlign: 'center' }}>
      <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.02em' }}>{value}</div>
      <Mono size={8.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
        {label}
      </Mono>
    </Card>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div style={{ margin: '26px 0 10px' }}>
      <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
        {children}
      </Mono>
    </div>
  )
}

function DomainCard({
  domain,
  onClick
}: {
  domain: Domain
  onClick: () => void
}): React.JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      className="interactive"
      style={{
        display: 'block',
        textAlign: 'left',
        background: 'var(--sur)',
        border: '1px solid var(--bd)',
        borderRadius: 4,
        padding: 16,
        cursor: 'pointer',
        color: 'var(--tx)',
        fontFamily: 'var(--font-ui)'
      }}
    >
      <span style={{ color: 'var(--acc)', display: 'inline-flex' }}>{domain.icon}</span>
      <div style={{ fontSize: 13.5, fontWeight: 600, marginTop: 10 }}>{domain.title}</div>
      <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 4, lineHeight: 1.5 }}>
        {domain.body}
      </div>
    </button>
  )
}
