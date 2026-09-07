// "Open on this machine" in the graph inspector (SOLUSDEV-249 / I2). When the
// focused entity is one a local folder landed AND this machine's local-folder
// view carries it, the same Open-in buttons as the LOCAL FOLDER card appear —
// built from the API's `open_targets`, disabled with the reason while the
// companion is offline, never from the renderer directly. Nothing renders
// when the view has no such entity: an entity from another machine's folder
// cannot be opened here, and the panel says nothing rather than guessing.
import { Mono } from '../../components/ui/Mono'
import type { Entity } from '../../lib/api/resources'
import { COMPANION_OFFLINE_NOTE } from '../project/localFolder.constants'
import { OpenInButtons } from '../project/OpenInButtons'
import { useProjectFolderStore } from '../project/projectFolderStore'
import { useLocalFolder } from '../project/useLocalFolder'

export interface LocalOpenPanelProps {
  projectId: string
  entity: Entity
}

export function LocalOpenPanel({
  projectId,
  entity
}: LocalOpenPanelProps): React.JSX.Element | null {
  const linked = useProjectFolderStore((s) => s.folders[projectId] !== undefined)
  const folder = useLocalFolder(projectId, linked)
  const view = folder.view
  const project = view?.detected.find((d) => d.entity_id === entity.id) ?? null
  if (!view || !project) return null
  const reason = view.bridge.connected ? null : COMPANION_OFFLINE_NOTE
  return (
    <section
      aria-label="Open on this machine"
      style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
    >
      <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
        OPEN ON THIS MACHINE
      </Mono>
      <OpenInButtons
        targets={project.open_targets}
        disabledReason={reason}
        onOpen={(tool) => folder.open(project.entity_id, tool)}
      />
      {reason && (
        <div role="note" style={{ fontSize: 10.5, color: 'var(--mut)', lineHeight: 1.5 }}>
          {reason}
        </div>
      )}
    </section>
  )
}
