import type { ReactNode } from 'react'
import type { Entity, SolusEntry, SolusSection } from '../../lib/api/resources'
import { CodeEnvironmentCard } from './CodeEnvironmentCard'
import { SolusComposer } from './SolusComposer'
import { formatSize, sectionCountLabel, type Composer } from './solusActions'
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
  count: number
  online: boolean
  composer: Composer | null
  onCompose: (next: Composer | null) => void
  onSubmit: (text: string) => Promise<void>
}
export function SolusNodeContent({
  projectId,
  entity,
  entry,
  section,
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
        onCancel={() => onCompose(null)}
        onSubmit={onSubmit}
      />
    )
  if (section)
    return (
      <SectionContent
        section={section}
        count={count}
        online={online}
        entity={entity}
        onCompose={onCompose}
      />
    )
  if (entry)
    return <EntryContent entry={entry} entity={entity} online={online} onCompose={onCompose} />
  return entity.type === 'solus_config' ? (
    <span>Project knowledge · zoom in to open sections</span>
  ) : null
}

function composerKey(composer: NonNullable<ContentProps['composer']>): string {
  return composer.kind + (composer.entry?.id ?? '')
}
function composerText(composer: NonNullable<ContentProps['composer']>): string {
  return composer.entry?.text ?? ''
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
  if (entry.section === 'code') return <CodeEnvironmentCard payload={entry.payload} />
  if (entry.section === 'hardware') {
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

function SectionContent({
  section,
  count,
  online,
  entity,
  onCompose
}: Pick<ContentProps, 'count' | 'online' | 'entity' | 'onCompose'> & {
  section: SolusSection
}): React.JSX.Element {
  return (
    <div className="solus-section-content">
      <span>{online ? sectionCountLabel(count) : '—'}</span>
      {section === 'errors' && <span>AUTO + YOU</span>}
      <button
        type="button"
        disabled={!online}
        onClick={() => onCompose({ section, kind: 'type', entityId: entity.id })}
      >
        Add a note
      </button>
    </div>
  )
}
