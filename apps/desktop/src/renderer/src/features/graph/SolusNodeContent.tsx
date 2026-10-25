import type { ReactNode } from 'react'
import type { Entity, SolusEntry, SolusSection } from '../../lib/api/resources'
import { CodeEnvironmentCard } from './CodeEnvironmentCard'
import { EnvironmentDivergences } from './EnvironmentDivergences'
import { HistoryList } from './HistoryList'
import { SolusComposer } from './SolusComposer'
import {
  formatSize,
  isHardwareConfig,
  sectionCountLabel,
  type Composer,
  type ComposerSubmit
} from './solusActions'
import { HardwareConfigPanel } from './hardware/HardwareConfigPanel'
interface EntryProps {
  entry: SolusEntry
  entity: Entity
  online: boolean
  onCompose: (next: Composer | null) => void
}
const MONO_BODY = { fontFamily: 'var(--font-mono)', fontSize: 10.5 } as const

export function EntryContent({ entry, entity, online, onCompose }: EntryProps): React.JSX.Element {
  return (
    <div className="solus-entry-content">
      {entry.kind === 'artifact' ? (
        <span>{[entry.media_type, formatSize(entry.size_bytes)].filter(Boolean).join(' · ')}</span>
      ) : (
        <>
          <p style={entry.section === 'errors' ? MONO_BODY : undefined}>{entry.text}</p>
          {entry.author === 'sol' && <span>filed by SOL</span>}
          <button
            type="button"
            disabled={!online}
            onClick={() =>
              onCompose({ section: entry.section, kind: 'edit', entry, entityId: entity.id })
            }
          >
            Edit note
          </button>
        </>
      )}
    </div>
  )
}
interface ContentProps {
  projectId?: string | null
  entity: Entity
  entry?: SolusEntry
  section: SolusSection | null
  /** Set for a `solus_subsection` node: new entries file under it. */
  subsection?: string | null
  count: number
  online: boolean
  composer: Composer | null
  onCompose: (next: Composer | null) => void
  onSubmit: ComposerSubmit
}
export function SolusNodeContent({
  projectId,
  entity,
  entry,
  section,
  subsection,
  count,
  online,
  composer,
  onCompose,
  onSubmit
}: ContentProps): ReactNode {
  if (entry?.kind === 'config')
    return <ConfigContent entry={entry} projectId={projectId} online={online} />
  if (composer?.entityId === entity.id)
    return (
      <SolusComposer
        key={composerKey(composer)}
        kind={composer.kind}
        initial={composerText(composer)}
        section={composer.section}
        subsection={composer.subsection}
        onCancel={() => onCompose(null)}
        onSubmit={onSubmit}
      />
    )
  if (isProjectView(section, subsection))
    return <ProjectView projectId={projectId} history={section === 'history'} />
  if (section) return <SectionContent section={section} count={count} online={online} />
  if (entry)
    return <EntryContent entry={entry} entity={entity} online={online} onCompose={onCompose} />
  return null
}

function composerKey(composer: NonNullable<ContentProps['composer']>): string {
  return composer.kind + (composer.entry?.id ?? '')
}
function composerText(composer: NonNullable<ContentProps['composer']>): string {
  return composer.entry?.text ?? ''
}

function isDivergences(section: string | null, subsection: string | null | undefined): boolean {
  return section === 'environment' && subsection === 'divergences'
}
function isProjectView(section: string | null, subsection: string | null | undefined): boolean {
  return section === 'history' || isDivergences(section, subsection)
}

/** SOLUSDEV-320: the views that read a project route rather than entries —
 *  the history section (owns no rows, so no composer) and environment/divergences. */
function ProjectView({
  projectId,
  history
}: {
  projectId?: string | null
  history: boolean
}): ReactNode {
  if (!projectId) return <p role="status">Open a project to see this.</p>
  return history ? (
    <HistoryList key={projectId} projectId={projectId} />
  ) : (
    <EnvironmentDivergences projectId={projectId} />
  )
}

function ConfigContent({
  entry,
  projectId,
  online
}: {
  entry: SolusEntry
  projectId?: string | null
  online: boolean
}): ReactNode {
  if (entry.section === 'environment' && entry.subsection === 'software')
    return <CodeEnvironmentCard payload={entry.payload} />
  if (isDivergences(entry.section, entry.subsection))
    return <ProjectView projectId={projectId} history={false} />
  if (isHardwareConfig(entry)) {
    const subject = entry.payload?.schema_version === 2 ? entry.payload.entity_id : null
    return projectId &&
      typeof subject === 'string' &&
      /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/iu.test(subject) ? (
      <HardwareConfigPanel
        key={`${projectId}:${subject}`}
        projectId={projectId}
        entityId={subject}
        online={online}
      />
    ) : (
      <p role="status">Configuration needs migration or a project reload.</p>
    )
  }
  return <p role="status">Unsupported configuration section.</p>
}

/** The card body for a section node: the real count only — adding lives in the side panel
 *  footer and the right-click menu (design template). */
function SectionContent({
  section,
  count,
  online
}: Pick<ContentProps, 'count' | 'online'> & { section: SolusSection }): React.JSX.Element {
  return (
    <div className="solus-section-content">
      <span>{online ? sectionCountLabel(count) : '—'}</span>
      {section === 'errors' && <span>AUTO + YOU</span>}
    </div>
  )
}
