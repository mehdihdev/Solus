// One detected serial device (SOLUSDEV-72). Renders EXACTLY what the backend
// claims — board or "Unknown device", usb_bridge as "MCU unknown", confidence
// as reported. The serial number is the identity discriminator; ambiguous or
// serial-less devices require an explicit user pick of the device path before
// connect (propose, never assert). User labels persist by serial number; a
// path-keyed label is marked unverified after replug.
import { useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { Mono } from '../../../components/ui/Mono'
import type { BenchDevice, BenchSession, SerialRealConfig } from '../../../lib/api/resources'
import { PICKER_FIELD_STYLE } from '../../onboarding/SelectionPicker'
import { SessionChip } from './SessionChip'
import { deviceLabelKey, isUnverifiedAfterReplug, useDeviceLabelStore } from './deviceLabelStore'
import { deviceTitle } from './presentation'

export interface DeviceRowProps {
  device: BenchDevice
  sessions: BenchSession[]
  /** Non-null ⇒ connecting is impossible (runner missing); the reason shows. */
  disabledReason: string | null
  /** Starts the real/serial session; resolves to an error text or null. */
  onConnect: (config: SerialRealConfig) => Promise<string | null>
  onStop: (sessionId: string) => void
}

/** The exact config the frozen contract asks for: always the serial number
 *  when the device has one; the confirmed path ONLY for an explicit pick. */
function serialConfig(device: BenchDevice, picked: boolean): SerialRealConfig {
  const config: SerialRealConfig = { provider: 'serial' }
  if (device.serial_number !== null) config.serial_number = device.serial_number
  if (picked) config.confirmed_device_path = device.device_path
  return config
}

/** Title + identity discriminator: serial (or its absence), vid:pid, confidence. */
function IdentityBlock({ device }: { device: BenchDevice }): React.JSX.Element {
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 13, fontWeight: 600 }}>{deviceTitle(device)}</div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 3 }}>
        {device.serial_number !== null ? (
          <Mono size={9.5} color="var(--tx)">
            {device.serial_number}
          </Mono>
        ) : (
          <Mono size={8.5} color="var(--warn, #d9822b)" style={{ letterSpacing: '0.06em' }}>
            NO SERIAL
          </Mono>
        )}
        <Mono size={8.5} color="var(--mut)">
          {device.vid}:{device.pid}
        </Mono>
        <Mono size={8.5} color="var(--mut)">
          CONFIDENCE {device.confidence}
        </Mono>
      </div>
    </div>
  )
}

/** The explicit pick an ambiguous/serial-less device needs before connect. */
function PickControl({
  device,
  picked,
  onPick
}: {
  device: BenchDevice
  picked: boolean
  onPick: (picked: boolean) => void
}): React.JSX.Element {
  return (
    <label
      style={{
        display: 'flex',
        gap: 8,
        alignItems: 'center',
        marginTop: 8,
        fontSize: 11.5,
        cursor: 'pointer'
      }}
    >
      <input
        type="checkbox"
        aria-label={`Use ${device.device_path}`}
        checked={picked}
        onChange={(e) => onPick(e.target.checked)}
      />
      <span>
        Use <Mono size={10}>{device.device_path}</Mono> — this identity can&apos;t be pinned
        automatically, so confirm the exact port.
      </span>
    </label>
  )
}

function RowNote({
  color = 'var(--mut)',
  text
}: {
  color?: string
  text: string
}): React.JSX.Element {
  return <div style={{ fontSize: 10.5, color, marginTop: 4 }}>{text}</div>
}

export function DeviceRow({
  device,
  sessions,
  disabledReason,
  onConnect,
  onStop
}: DeviceRowProps): React.JSX.Element {
  const [picked, setPicked] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const labelKey = deviceLabelKey(device)
  const label = useDeviceLabelStore((s) => s.labels[labelKey] ?? '')
  const setLabel = useDeviceLabelStore((s) => s.setLabel)

  // Ambiguous (shared/absent serial) or serial-less: connecting must send a
  // user-confirmed device path, so the pick is required before connect.
  const needsPick = device.ambiguous || device.serial_number === null

  const connect = async (): Promise<void> => {
    setError(null)
    setError(await onConnect(serialConfig(device, needsPick && picked)))
  }

  return (
    <div style={{ padding: '12px 0', borderBottom: '1px solid var(--bd)' }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <IdentityBlock device={device} />
        <input
          aria-label={`Label for ${device.device_path}`}
          placeholder="Label (e.g. leader)"
          value={label}
          onChange={(e) => setLabel(labelKey, e.target.value)}
          style={{ ...PICKER_FIELD_STYLE, width: 130 }}
        />
        <Button
          kind="primary"
          size="sm"
          aria-label={`Connect ${device.device_path}`}
          disabled={disabledReason !== null || (needsPick && !picked)}
          onClick={() => void connect()}
        >
          Connect
        </Button>
      </div>
      {label !== '' && isUnverifiedAfterReplug(device) && (
        <RowNote
          text={`Label bound to ${device.vid}:${device.pid} at ${device.device_path} — unverified after replug (no serial number to pin it).`}
        />
      )}
      {needsPick && <PickControl device={device} picked={picked} onPick={setPicked} />}
      {device.note && <RowNote text={device.note} />}
      {disabledReason && <RowNote text={disabledReason} />}
      {error && <RowNote color="var(--err)" text={error} />}
      {sessions.map((session) => (
        <SessionChip key={session.id} session={session} onStop={onStop} />
      ))}
    </div>
  )
}
