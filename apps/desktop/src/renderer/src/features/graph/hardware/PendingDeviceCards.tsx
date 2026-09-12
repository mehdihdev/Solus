// The canvas-edge rail (SOLUSDEV-250 P3): the same pending devices as Add ›
// Hardware, compact, docked at the navigator viewport's right edge. Nothing
// when nothing is pending; a pill past three cards.
import { useMemo, useState } from 'react'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { useDetectedDevices } from './detectedDevicesStore'
import { DevicesFound } from './DevicesFound'
import { pendingDevices } from './deviceCard'

export interface PendingDeviceCardsProps {
  projectId: string
  mode: SolMode
  robots: readonly Entity[]
  entities: readonly Entity[] | null
  onCreated: (entity: Entity) => void
}

const MAX_OPEN = 3
// ponytail: the count ignores session dismissals (they live in the proposal
// hook); lift `dismissed` into the store if the pill threshold must be exact.
const NONE: ReadonlySet<string> = new Set()

export function PendingDeviceCards(props: PendingDeviceCardsProps): React.JSX.Element | null {
  const { devices } = useDetectedDevices()
  const [expanded, setExpanded] = useState(false)
  const count = useMemo(
    () => pendingDevices(devices ?? [], props.entities, NONE).length,
    [devices, props.entities]
  )
  if (count === 0) return null
  const collapsible = count > MAX_OPEN
  return (
    <div className="pending-devices">
      {collapsible && (
        <button
          type="button"
          className="pending-devices-pill"
          onClick={() => setExpanded((open) => !open)}
        >
          {expanded ? 'Hide devices' : `${count} devices found`}
        </button>
      )}
      {(!collapsible || expanded) && <DevicesFound {...props} compact />}
    </div>
  )
}
