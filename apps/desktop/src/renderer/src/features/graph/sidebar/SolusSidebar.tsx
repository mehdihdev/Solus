// The sidebar for .solus nodes (SOLUSDEV-250 P4): the root's five counts, a section's
// three W1 actions with the inline composer and its entries, an entry's content with
// Edit and the two-step delete. The context menu offers the same actions; this is where
// its Delete lands. Below every branch: the focus summary and "Ask SOL about this".
import type { ReactNode } from 'react'
import {
  SOLUS_SECTIONS,
  type Entity,
  type SolusEntry,
  type SolusSection
} from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { useFocusStore } from '../../workspace/focusStore'
import { FocusSummaryWidget } from '../../workspace/widgets/FocusSummaryWidget'
import { WidgetHost } from '../../workspace/widgets/WidgetHost'
import { SolusComposer } from '../SolusComposer'
import { SolusNodeContent } from '../SolusNodeContent'
import { entryTitle, sectionCountLabel, sectionMenuItems, type Composer } from '../solusActions'
import { SECTION_LABELS, type SolusState } from '../useSolusConfig'
import { TwoStepDelete } from './TwoStepDelete'

export interface SolusSidebarProps {
  projectId?: string | null
  entity: Entity
  entry?: SolusEntry
  section: SolusSection | null
  state: SolusState
  mode: SolMode
  composer: Composer | null
  setComposer: (next: Composer | null) => void
  onSubmit: (text: string) => Promise<void>
  remove: (entry: SolusEntry) => Promise<boolean>
  onImport: (section: SolusSection) => void
  streaming: boolean
  online: boolean
  armedDeleteId: string | null
  armDelete: (entry: SolusEntry) => void
  disarm: () => void
}

const COPY = {
  root: {
    Guide:
      'Project knowledge SOL reads first. Zoom into a section to import files, ask SOL, or type a note.',
    Expert: 'Project knowledge · zoom in to open sections.'
  },
  empty: {
    Guide: 'Nothing filed here yet — import files, ask SOL to find them, or type it.',
    Expert: 'Empty.'
  }
} as const

function Root({ state, mode }: Pick<SolusSidebarProps, 'state' | 'mode'>): React.JSX.Element {
  return (
    <>
      <h2>.solus</h2>
      <p>{COPY.root[mode]}</p>
      <ul>
        {SOLUS_SECTIONS.map((key) => (
          <li key={key}>
            <span>{SECTION_LABELS[key]}</span>
            <code className="node-sidebar-mono">
              {state.status === 'ready' ? sectionCountLabel(state.sections[key].length) : '—'}
            </code>
          </li>
        ))}
      </ul>
    </>
  )
}

function Section({
  entity,
  section,
  state,
  mode,
  composer,
  setComposer,
  onSubmit,
  onImport,
  streaming,
  online
}: SolusSidebarProps & { section: SolusSection }): React.JSX.Element {
  const entries = state.sections[section]
  const items = sectionMenuItems(section, streaming, onImport, (next) =>
    setComposer({ ...next, entityId: entity.id })
  )
  return (
    <>
      <h2>{SECTION_LABELS[section]}</h2>
      {online && composer?.entityId === entity.id ? (
        <SolusComposer
          key={composer.kind}
          kind={composer.kind}
          initial=""
          onCancel={() => setComposer(null)}
          onSubmit={onSubmit}
        />
      ) : (
        online && (
          <div className="node-sidebar-actions" role="group" aria-label="Section actions">
            {items.map((item) => (
              <span key={item.label}>
                <button
                  type="button"
                  className="node-sidebar-link"
                  disabled={item.disabled}
                  onClick={item.onSelect}
                >
                  {item.label}
                </button>
                {item.disabled && item.hint && <p>{item.hint}</p>}
              </span>
            ))}
          </div>
        )
      )}
      {entries.length === 0 ? (
        <p>{COPY.empty[mode]}</p>
      ) : (
        <ul>
          {entries.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className="node-sidebar-link"
                disabled={!item.entity_id}
                onClick={() =>
                  item.entity_id && void useFocusStore.getState().focus(item.entity_id)
                }
              >
                {entryTitle(item)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

function Entry({
  projectId,
  entity,
  entry,
  composer,
  setComposer,
  onSubmit,
  remove,
  online,
  armedDeleteId,
  armDelete,
  disarm
}: SolusSidebarProps & { entry: SolusEntry }): React.JSX.Element {
  const file = entry.kind === 'artifact'
  return (
    <>
      <h2>{entry.name ?? (entry.kind === 'sol' ? 'SOL note' : 'Note')}</h2>
      <SolusNodeContent
        projectId={projectId}
        entity={entity}
        entry={entry}
        section={null}
        count={0}
        online={online}
        composer={composer}
        onCompose={setComposer}
        onSubmit={onSubmit}
      />
      {online && !(entry.kind === 'config' && entry.section === 'hardware') && (
        <TwoStepDelete
          label={entry.kind === 'config' ? 'Delete record' : file ? 'Delete file' : 'Delete note'}
          detail={
            entry.kind === 'config'
              ? `Delete this CODE record and its graph links? The environment remains on your computer.`
              : `Delete "${entryTitle(entry)}" from .solus? Its graph node and ${file ? 'stored bytes' : 'links'} go with it.`
          }
          armed={armedDeleteId === entry.id}
          onArm={() => armDelete(entry)}
          onDisarm={disarm}
          onConfirm={() => remove(entry)}
        />
      )}
    </>
  )
}

export function SolusSidebar(props: SolusSidebarProps): ReactNode {
  const { entry, section } = props
  return (
    <>
      {entry ? (
        <Entry {...props} entry={entry} />
      ) : section ? (
        <Section {...props} section={section} />
      ) : (
        <Root {...props} />
      )}
      {/* ponytail: no onSolAction — SOL routing lands with WS-04; the host's documented no-op applies */}
      <WidgetHost widget={FocusSummaryWidget} />
    </>
  )
}
