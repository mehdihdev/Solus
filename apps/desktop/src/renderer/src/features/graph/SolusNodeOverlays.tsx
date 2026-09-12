import { useEffect } from 'react'
import { ContextMenu } from '../../components/ui/ContextMenu'
import type { SolusEntry, SolusSection } from '../../lib/api/resources'
import { DeleteConfirmModal } from '../workspace/modals'
import { SECTION_LABELS } from './useSolusConfig'
import { entryMenuItems, sectionMenuItems, type Composer } from './solusActions'

export interface Menu {
  x: number
  y: number
  section: SolusSection
  entityId: string
  entry?: SolusEntry
}
export function EntryDelete({
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
      noun={entry.kind === 'config' ? 'record' : entry.kind === 'artifact' ? 'file' : 'note'}
      detail={
        entry.kind === 'config'
          ? 'from .solus, including its graph node and links. The environment remains on your computer.'
          : entry.kind === 'artifact'
            ? 'from .solus — its graph node and stored bytes go with it'
            : 'from .solus, including its graph node and links'
      }
      onClose={onClose}
      onConfirm={onConfirm}
    />
  )
}

export function NodeMenu({
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
