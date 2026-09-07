// The Hardware tab of the workspace Add panel (SOLUSDEV-248 R1): five entry
// cards in a compact 2-column grid, each opening its own ModalShell flow.
// Offline → every card is disabled with honest copy; nothing is fabricated.
import { useState } from 'react'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { AuthoredPartModal } from './AuthoredPartModal'
import { DetectedModal } from './DetectedModal'
import { FromFileModal } from './FromFileModal'
import { HardwareCard } from './HardwareCard'
import { HARDWARE_CARDS, HARDWARE_COPY, type HardwareCardId } from './hardware.constants'
import { LibraryModal } from './LibraryModal'

export interface HardwareAddPanelProps {
  projectId: string
  online: boolean
  mode: SolMode
  /** Existing physical_robot entities for the Detected, From a file, Library and Authored targets. */
  robots: readonly Entity[]
  createRobot: () => Promise<string>
  onCreated: (entity: Entity) => void
}

export function HardwareAddPanel({
  projectId,
  online,
  mode,
  robots,
  createRobot,
  onCreated
}: HardwareAddPanelProps): React.JSX.Element {
  const [open, setOpen] = useState<HardwareCardId | null>(null)
  const close = (): void => setOpen(null)
  return (
    <div className="hardware-add">
      <p style={{ fontSize: 12, color: 'var(--mut)', margin: '0 0 12px', lineHeight: 1.5 }}>
        {HARDWARE_COPY.intro[mode]}
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {HARDWARE_CARDS.map((card) => (
          <HardwareCard
            key={card.id}
            card={card}
            disabled={!online || card.disabled === true}
            onOpen={() => setOpen(card.id)}
          />
        ))}
      </div>
      {!online && (
        <p style={{ fontSize: 12, color: 'var(--mut)' }}>Connect this project to add hardware.</p>
      )}
      {open === 'detected' && (
        <DetectedModal
          projectId={projectId}
          mode={mode}
          robots={robots}
          onCreated={onCreated}
          onClose={close}
        />
      )}
      {open === 'file' && (
        <FromFileModal projectId={projectId} mode={mode} robots={robots} onClose={close} />
      )}
      {open === 'library' && (
        <LibraryModal
          projectId={projectId}
          mode={mode}
          robots={robots}
          onCreated={onCreated}
          onClose={close}
        />
      )}
      {open === 'authored' && (
        <AuthoredPartModal
          projectId={projectId}
          robots={robots}
          mode={mode}
          createRobot={createRobot}
          onCreated={onCreated}
          onClose={close}
        />
      )}
    </div>
  )
}
