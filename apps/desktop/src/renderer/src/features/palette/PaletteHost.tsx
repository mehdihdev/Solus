// SOLUSDEV-317 — mounts the ⌘K palette in the workspace shell: owns the
// shortcut, and only while open reads the live data it searches (the user's
// teams and projects; the OPEN project's graph through the same retained
// snapshot the Workspace screen uses, so reopening is instant).
import { useMemo } from 'react'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useWorkspaceGraph } from '../graph/useWorkspaceGraph'
import { useProjectSwitcher } from '../workspace/useProjectSwitcher'
import { CommandPalette } from './CommandPalette'
import { runPaletteTarget, type PaletteActions } from './paletteActions'
import { reportPaletteOpened } from './paletteEvents'
import { usePaletteHotkey } from './paletteHotkey'
import { nodeItems, pageItems, projectItems, teamItems, type PaletteItem } from './paletteItems'
import { usePaletteStore } from './paletteStore'

export interface PaletteHostProps extends PaletteActions {
  /** The rail's extension page views (installed or pinned). */
  extensions: readonly { slug: string; label: string }[]
}

const togglePalette = (): void => usePaletteStore.getState().toggle()

export function PaletteHost(props: PaletteHostProps): React.JSX.Element | null {
  const open = usePaletteStore((s) => s.open)
  usePaletteHotkey(togglePalette)
  return open ? <OpenPalette {...props} /> : null
}

function OpenPalette({ extensions, go, openExtensionPage }: PaletteHostProps): React.JSX.Element {
  const switcher = useProjectSwitcher()
  const graph = useWorkspaceGraph()
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const recentKeys = usePaletteStore((s) => s.recentKeys)
  const items = useMemo(
    () => [
      ...pageItems(extensions),
      ...projectItems(switcher.groups),
      ...teamItems(switcher.groups),
      ...(projectId ? nodeItems(projectId, graph.entities) : [])
    ],
    [extensions, switcher.groups, projectId, graph.entities]
  )
  const close = (): void => usePaletteStore.getState().setOpen(false)
  const onPick = (item: PaletteItem, rank: number, query: string): void => {
    close()
    usePaletteStore.getState().remember(item.key)
    reportPaletteOpened(item.kind, rank, query)
    runPaletteTarget(item.target, { go, openExtensionPage })
  }
  return (
    <CommandPalette
      items={items}
      recentKeys={recentKeys}
      loading={switcher.status === 'loading' || (projectId !== null && graph.status === 'loading')}
      hasProject={projectId !== null}
      onPick={onPick}
      onClose={close}
    />
  )
}
