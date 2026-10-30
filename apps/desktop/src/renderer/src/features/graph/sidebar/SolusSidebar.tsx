// The sidebar for .solus nodes (SOLUSDEV-250 P4): the root's seven counts, a section's
// (or subsection's) three W1 actions with the inline composer and its entries, an entry's
// content with Edit and the two-step delete. The context menu offers the same actions;
// this is where its Delete lands. Below every branch: the focus summary and "Ask SOL
// about this".
import type { ReactNode } from 'react'
import {
  SOLUS_SECTIONS,
  type Entity,
  type SolusEntry,
  type SolusSection
} from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { Button } from '../../../components/ui/Button'
import { Mono } from '../../../components/ui/Mono'
import { useFocusStore } from '../../workspace/focusStore'
import { NodePanelFooter } from './PanelChrome'
import { SolusComposer } from '../SolusComposer'
import { SolusNodeContent } from '../SolusNodeContent'
import {
  entriesIn,
  entryTitle,
  isHardwareConfig,
  sectionCountLabel,
  targetLabel,
  type Composer,
  type ComposerSubmit
} from '../solusActions'
import { SECTION_LABELS, type SolusState } from '../useSolusConfig'
import { TwoStepDelete } from './TwoStepDelete'

export interface SolusSidebarProps {
  projectId?: string | null
  entity: Entity
  entry?: SolusEntry
  section: SolusSection | null
  /** Set for a `solus_subsection` node: the list and the actions narrow to it. */
  subsection?: string | null
  state: SolusState
  mode: SolMode
  composer: Composer | null
  setComposer: (next: Composer | null) => void
  onSubmit: ComposerSubmit
  remove: (entry: SolusEntry) => Promise<boolean>
  onImport: (section: SolusSection, subsection?: string | null) => void
  streaming: boolean
  online: boolean
  armedDeleteId: string | null
  armDelete: (entry: SolusEntry) => void
  disarm: () => void
  /** The footer's Ask SOL; absent → the button is not offered. */
  onAskSol?: () => void
}

const COPY = {
  empty: {
    Guide: 'Nothing filed here yet — use Add / Edit or Upload below, or ask SOL to find it.',
    Expert: 'Empty.'
  }
} as const

function Root({ state }: Pick<SolusSidebarProps, 'state'>): React.JSX.Element {
  return (
    <>
      <h2>.solus</h2>
      <div className="node-panel-section-row">
        <Mono size={10} ls="0.08em">
          NODES UNDERNEATH
        </Mono>
        <Mono size={10}>{SOLUS_SECTIONS.length} sections</Mono>
      </div>
      <ul className="node-panel-list">
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
  subsection,
  state,
  mode,
  composer,
  setComposer,
  onSubmit,
  online
}: SolusSidebarProps & { section: SolusSection }): React.JSX.Element {
  const entries = entriesIn(state.sections, section, subsection)
  return (
    <>
      <h2>{targetLabel(section, subsection)}</h2>
      {online && composer?.entityId === entity.id && (
        <SolusComposer
          key={composer.kind}
          kind={composer.kind}
          initial=""
          section={section}
          subsection={composer.subsection}
          onCancel={() => setComposer(null)}
          onSubmit={onSubmit}
        />
      )}
      <div className="node-panel-section-row">
        <Mono size={10} ls="0.08em">
          CONTENTS
        </Mono>
        <Mono size={10}>{sectionCountLabel(entries.length).toLowerCase()}</Mono>
      </div>
      {entries.length === 0 ? (
        <p>{COPY.empty[mode]}</p>
      ) : (
        <ul className="node-panel-list">
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
      <Mono size={10} ls="0.08em">
        CONTENT OVERVIEW
      </Mono>
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
      {online && !isHardwareConfig(entry) && (
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

interface FooterModel {
  editable: boolean
  upload: { section: SolusSection; subsection?: string | null } | null
}

/** What the footer may do here: notes edit, files and records don't; uploads land where the node points. */
function footerModel(
  entry: SolusEntry | undefined,
  section: SolusSection | null,
  subsection: string | null | undefined
): FooterModel {
  if (entry)
    return {
      editable: entry.kind === 'text' || entry.kind === 'sol',
      upload: { section: entry.section, subsection: entry.subsection }
    }
  return { editable: section !== null, upload: section ? { section, subsection } : null }
}

/** The design's three footer actions, wired to the handlers this panel already owns. */
function Footer({
  entity,
  entry,
  section,
  subsection,
  online,
  setComposer,
  onImport,
  onAskSol
}: SolusSidebarProps): React.JSX.Element {
  const { editable, upload } = footerModel(entry, section, subsection)
  const edit = (): void => {
    if (entry) setComposer({ kind: 'edit', section: entry.section, entry, entityId: entity.id })
    else if (section) setComposer({ kind: 'type', section, subsection, entityId: entity.id })
  }
  return (
    <NodePanelFooter>
      {(editable || !entry) && (
        <Button kind="soft" disabled={!online || !editable} onClick={edit}>
          {entry ? 'Edit' : 'Add / Edit'}
        </Button>
      )}
      <Button
        kind="soft"
        disabled={!online || !upload}
        onClick={() => upload && onImport(upload.section, upload.subsection)}
      >
        Upload
      </Button>
      {onAskSol && (
        <Button kind="primary" onClick={onAskSol}>
          Ask SOL
        </Button>
      )}
    </NodePanelFooter>
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
      <Footer {...props} />
    </>
  )
}
