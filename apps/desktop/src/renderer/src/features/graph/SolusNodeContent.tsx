import type { ReactNode } from 'react'
import type { Entity, SolusEntry, SolusSection } from '../../lib/api/resources'
import { SolusComposer } from './SolusComposer'
import { formatSize, sectionCountLabel, type Composer } from './solusActions'
interface EntryProps {
  entry: SolusEntry
  entity: Entity
  online: boolean
  onCompose: (next: Composer | null) => void
}
function EntryContent({ entry, entity, online, onCompose }: EntryProps): React.JSX.Element {
  return (
    <div className="solus-entry-content">
      {entry.kind === 'artifact' ? (
        <span>{[entry.media_type, formatSize(entry.size_bytes)].filter(Boolean).join(' · ')}</span>
      ) : (
        <>
          <p>{entry.text}</p>
          {entry.kind === 'sol' && <span>filed by SOL</span>}
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
  entity,
  entry,
  section,
  count,
  online,
  composer,
  onCompose,
  onSubmit
}: ContentProps): ReactNode {
  if (composer?.entityId === entity.id)
    return (
      <SolusComposer
        key={composer.kind + (composer.entry?.id ?? '')}
        kind={composer.kind}
        initial={composer.entry?.text ?? ''}
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
