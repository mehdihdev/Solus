import { NodeMenu, type Menu } from './SolusNodeOverlays'
import { useCallback, type ReactNode, useRef, useState } from 'react'
import { clampMenuPosition } from '../../components/ui/ContextMenu'
import {
  SOLUS_SECTIONS,
  type Entity,
  type SolusEntry,
  type SolusSection
} from '../../lib/api/resources'
import { useSettingsStore } from '../../store/settingsStore'
import { selectSession, useSolChatStore } from '../sol/solChatStore'
import { useFocusStore } from '../workspace/focusStore'
import { SolusSidebar } from './sidebar/SolusSidebar'
import { useSolusConfig, type SolusState } from './useSolusConfig'
import { SolusNodeContent } from './SolusNodeContent'
import { findSolusEntry, useSolusActions, type Composer } from './solusActions'

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
  /** The hidden file input and the context menu — no modals (SOLUSDEV-250 P4). */
  overlays: ReactNode
  renderSidebar: (entity: Entity) => ReactNode
}

/** Attach W1 actions to persisted graph identities; never synthesize graph nodes. */
function useSolusNodeActions(projectId: string | null, onGraphChanged: () => void) {
  const state = useSolusConfig(projectId)
  const mode = useSettingsStore((s) => s.solMode)
  const streaming = useSolChatStore((s) => selectSession(s, projectId).streaming)
  const actions = useSolusActions(projectId, state, onGraphChanged)
  const [menu, setMenu] = useState<Menu | null>(null)
  const [composer, setComposer] = useState<Composer | null>(null)
  const [armedDeleteId, setArmedDeleteId] = useState<string | null>(null)
  const { input, onImport } = useSolusImport(actions.importFile)
  const online = state.status === 'ready' && projectId !== null
  const sections = state.sections
  const onContextMenu = useCallback(
    (event: React.MouseEvent, entity: Entity): void => {
      const entry = findSolusEntry(sections, entity.id)
      if (entry?.kind === 'config' && entry.section === 'hardware') {
        event.preventDefault()
        return
      }
      const section = entry?.section ?? sectionOf(entity)
      if (!section || !online) return
      event.preventDefault()
      setMenu({
        section,
        entry,
        entityId: entity.id,
        ...clampMenuPosition(event.clientX, event.clientY)
      })
    },
    [sections, online]
  )
  // The menu's Delete lands in the sidebar: focus the entry, arm its confirm step.
  const armDelete = (entry: SolusEntry): void => {
    if (entry.entity_id) void useFocusStore.getState().focus(entry.entity_id)
    setArmedDeleteId(entry.id)
  }
  // Latest-ref: the actions object is rebuilt every render; the card callbacks must not be.
  const submit = useRef(actions.submit)
  submit.current = actions.submit
  const onSubmit = useCallback(
    async (text: string): Promise<void> => {
      if (composer && (await submit.current(composer, text))) setComposer(null)
    },
    [composer]
  )
  return {
    state,
    mode,
    streaming,
    actions,
    menu,
    setMenu,
    composer,
    setComposer,
    armedDeleteId,
    setArmedDeleteId,
    input,
    onImport,
    online,
    sections,
    onContextMenu,
    armDelete,
    onSubmit
  }
}

export function useSolusNodes(projectId: string | null, onGraphChanged: () => void): SolusNodes {
  const {
    state,
    mode,
    streaming,
    actions,
    menu,
    setMenu,
    composer,
    setComposer,
    armedDeleteId,
    setArmedDeleteId,
    input,
    onImport,
    online,
    sections,
    onContextMenu,
    armDelete,
    onSubmit
  } = useSolusNodeActions(projectId, onGraphChanged)
  const overlays = (
    <>
      {input}
      {menu && (
        <NodeMenu
          menu={menu}
          streaming={streaming}
          onCompose={setComposer}
          onDelete={armDelete}
          onImport={onImport}
          onClose={() => setMenu(null)}
        />
      )}
    </>
  )
  const renderContent = useCallback(
    (entity: Entity): ReactNode => {
      const section = sectionOf(entity)
      return (
        <SolusNodeContent
          projectId={projectId}
          entity={entity}
          entry={findSolusEntry(sections, entity.id)}
          section={section}
          count={section ? sections[section].length : 0}
          online={online}
          composer={composer}
          onCompose={setComposer}
          onSubmit={onSubmit}
        />
      )
    },
    [projectId, sections, online, composer, onSubmit, setComposer]
  )
  const renderSidebar = (entity: Entity): ReactNode => (
    <SolusSidebar
      key={entity.id}
      projectId={projectId}
      entity={entity}
      entry={findSolusEntry(state.sections, entity.id)}
      section={sectionOf(entity)}
      state={state}
      mode={mode}
      composer={composer}
      setComposer={setComposer}
      onSubmit={onSubmit}
      remove={actions.remove}
      onImport={onImport}
      streaming={streaming}
      online={online}
      armedDeleteId={armedDeleteId}
      armDelete={armDelete}
      disarm={() => setArmedDeleteId(null)}
    />
  )
  return { state, onContextMenu, renderContent, overlays, renderSidebar }
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
