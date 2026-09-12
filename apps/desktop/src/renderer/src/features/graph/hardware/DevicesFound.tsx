// The live list of pending device cards (SOLUSDEV-250 P3): every device on
// this machine that no robot owns yet, each a DeviceCard. Rendered by Add ›
// Hardware and, compact, by the canvas-edge rail — both share one proposal state.
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { useDetectedDevices } from './detectedDevicesStore'
import { DeviceCard } from './DeviceCard'
import { useDeviceProposals } from './useDeviceProposals'

export interface DevicesFoundProps {
  projectId: string
  mode: SolMode
  robots: readonly Entity[]
  entities: readonly Entity[] | null
  onCreated: (entity: Entity) => void
  compact?: boolean
}

const NO_DEVICES: Record<SolMode, string> = {
  Guide:
    'Nothing found yet. Plug in a USB device, a CAN adapter, or join the robot’s network — it ' +
    'appears here the moment it does.',
  Expert: 'Nothing found yet.'
}

export function DevicesFound({
  projectId,
  mode,
  robots,
  entities,
  onCreated,
  compact = false
}: DevicesFoundProps): React.JSX.Element | null {
  const { devices } = useDetectedDevices()
  const { cards, confirm, accept, dismiss, retry } = useDeviceProposals(
    projectId,
    devices,
    entities
  )
  if (devices === null)
    return compact ? null : (
      <p role="status" className="devices-found-empty">
        Looking for devices…
      </p>
    )
  if (cards.length === 0)
    return compact ? null : <p className="devices-found-empty">{NO_DEVICES[mode]}</p>
  return (
    <ul className="devices-found" aria-label="Devices found">
      {cards.map((card) => (
        <li key={card.ref}>
          <DeviceCard
            state={card}
            robots={robots}
            mode={mode}
            compact={compact}
            onConfirm={(input) =>
              void confirm(card.ref, input).then((out) => out && onCreated(out.robot))
            }
            onAccept={(suggestion) =>
              void accept(card.ref, suggestion.id).then((ok) => {
                const robot = robots.find((r) => r.id === suggestion.candidate_robot_id)
                if (ok && robot) onCreated(robot)
              })
            }
            onDismiss={() => dismiss(card.ref)}
            onRetry={() => retry(card.ref)}
          />
        </li>
      ))}
    </ul>
  )
}
