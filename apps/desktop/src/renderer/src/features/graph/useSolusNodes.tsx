import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ContextMenu, clampMenuPosition } from '../../components/ui/ContextMenu'
import {
  SOLUS_SECTIONS,
  type Entity,
  type SolusEntry,
  type SolusSection
} from '../../lib/api/resources'
import { selectSession, useSolChatStore } from '../sol/solChatStore'
import { DeleteConfirmModal } from '../workspace/modals'
import { SECTION_LABELS, useSolusConfig, type SolusState } from './useSolusConfig'
import { SolusNodeContent } from './SolusNodeContent'
import { entryMenuItems, sectionMenuItems, useSolusActions, type Composer } from './solusActions'

interface Menu {
  x: number
  y: number
  section: SolusSection
  entityId: string
  entry?: SolusEntry
}
function sectionOf(entity: Entity): SolusSection | null {
  const section = entity.properties?.section
  return entity.type === 'solus_section' && SOLUS_SECTIONS.some((key) => key === section)
    ? (section as SolusSection)
    : null
}

interface SolusNodes {
  state: SolusState
  onContextMenu: (event: React.MouseEvent, entity: Entity) => void
  renderContent: (entity: Entity) => ReactNode
  overlays: ReactNode
}

/** Attach W1 actions to persisted graph identities; never synthesize graph nodes. */
export function useSolusNodes(projectId: string | null, onGraphChanged: () => void): SolusNodes {
  const state = useSolusConfig(projectId)
  const streaming = useSolChatStore((s) => selectSession(s, projectId).streaming)
  const actions = useSolusActions(projectId, state, onGraphChanged)
  const [menu, setMenu] = useState<Menu | null>(null)
  const [composer, setComposer] = useState<Composer | null>(null)
  const [pendingDelete, setPendingDelete] = useState<SolusEntry | null>(null)
  const { input, onImport } = useSolusImport(actions.importFile)
  const entries = new Map(
    Object.values(state.sections)
      .flat()
      .map((entry) => [entry.entity_id, entry])
  )
  const online = state.status === 'ready' && projectId !== null
  const onContextMenu = (event: React.MouseEvent, entity: Entity): void => {
    const entry = entries.get(entity.id)
    const section = entry?.section ?? sectionOf(entity)
    if (!section || !online) return
    event.preventDefault()
    setMenu({
      section,
      entry,
      entityId: entity.id,
      ...clampMenuPosition(event.clientX, event.clientY)
    })
  }
  const onDelete = (entry: SolusEntry): void => setPendingDelete(entry)
  const onSubmit = async (text: string): Promise<void> => {
    if (composer && (await actions.submit(composer, text))) setComposer(null)
  }
  const overlays = (
    <>
      {input}
      {menu && (
        <NodeMenu
          menu={menu}
          streaming={streaming}
          onCompose={setComposer}
          onDelete={onDelete}
          onImport={onImport}
          onClose={() => setMenu(null)}
        />
      )}
      {pendingDelete && (
        <EntryDelete
          entry={pendingDelete}
          onClose={() => setPendingDelete(null)}
          onConfirm={() => actions.remove(pendingDelete)}
        />
      )}
    </>
  )
  const renderContent = (entity: Entity): ReactNode => {
    const section = sectionOf(entity)
    return (
      <SolusNodeContent
        entity={entity}
        entry={entries.get(entity.id)}
        section={section}
        count={section ? state.sections[section].length : 0}
        online={online}
        composer={composer}
        onCompose={setComposer}
        onSubmit={onSubmit}
      />
    )
  }
  return { state, onContextMenu, renderContent, overlays }
}

function EntryDelete({
  entry,
  onClose,
  onConfirm
}: {
  entry: SolusEntry
  onClose: () => void
  onConfirm: () => Promise<boolean>
}): React.JSX.Element {
  return (
    <DeleteConfirmModal
      name={entry.name ?? entry.text?.slice(0, 120) ?? 'this note'}
      noun={entry.kind === 'artifact' ? 'file' : 'note'}
      detail={
        entry.kind === 'artifact'
          ? 'from .solus — its graph node and stored bytes go with it'
          : 'from .solus, including its graph node and links'
      }
      onClose={onClose}
      onConfirm={onConfirm}
    />
  )
}

function NodeMenu({
  menu,
  streaming,
  onCompose,
  onDelete,
  onImport,
  onClose
}: {
  menu: Menu
  streaming: boolean
  onCompose: (next: Composer) => void
  onDelete: (entry: SolusEntry) => void
  onImport: (section: SolusSection) => void
  onClose: () => void
}): React.JSX.Element {
  useEffect(() => {
    const dismiss = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopPropagation()
      onClose()
    }
    document.addEventListener('keydown', dismiss, true)
    return () => document.removeEventListener('keydown', dismiss, true)
  }, [onClose])
  const compose = (next: Composer): void => onCompose({ ...next, entityId: menu.entityId })
  return (
    <ContextMenu
      x={menu.x}
      y={menu.y}
      title={menu.entry ? undefined : SECTION_LABELS[menu.section]}
      items={
        menu.entry
          ? entryMenuItems(menu.entry, compose, onDelete)
          : sectionMenuItems(menu.section, streaming, onImport, compose)
      }
      onClose={onClose}
    />
  )
}

function useSolusImport(importFile: (section: SolusSection, file: File) => Promise<void>) {
  const fileInput = useRef<HTMLInputElement | null>(null)
  const importTarget = useRef<SolusSection | null>(null)
  const onImport = (section: SolusSection): void => {
    importTarget.current = section
    fileInput.current?.click()
  }
  const input = (
    <input
      ref={fileInput}
      type="file"
      aria-label="Import a file into .solus"
      style={{ display: 'none' }}
      onChange={(event) => {
        const file = event.currentTarget.files?.[0]
        event.currentTarget.value = ''
        if (file && importTarget.current) void importFile(importTarget.current, file)
      }}
    />
  )
  return { input, onImport }
}
