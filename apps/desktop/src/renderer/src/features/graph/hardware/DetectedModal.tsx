// Flow 1 — Detected (docs/wireflows/hardware-onboarding.md): the live device
// list at whichever level is honestly known, then Propose → ProposalView.
// Every row is the backend's claim; runner absent / unreachable is said as-is.
import { useEffect, useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { Spinner } from '../../../components/ui/Spinner'
import {
  listDetectedDevices,
  proposeDetected,
  type DetectedDeviceOut,
  type ProposalOut
} from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { ModalShell } from '../../workspace/modals'
import { detectedIdentity, detectedTitle, hardwareErrorText } from './detected'
import { CloseFooter } from './HardwareInfoModals'
import { HARDWARE_COPY } from './hardware.constants'
import { ProposalView } from './ProposalView'

export interface DetectedModalProps {
  projectId: string
  mode: SolMode
  /** Existing physical_robot entities for the "Add to [robot]" target. */
  robots: readonly Entity[]
  onCreated: (entity: Entity) => void
  onClose: () => void
}

type DeviceRead =
  | { phase: 'loading' }
  | { phase: 'error'; message: string }
  | { phase: 'ready'; devices: DetectedDeviceOut[] }

const MONO_STYLE = { fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--mut)' } as const
const BODY_STYLE = { fontSize: 12.5, color: 'var(--mut)', marginTop: 8, lineHeight: 1.55 } as const

function DeviceRowItem({
  device,
  busy,
  onPropose
}: {
  device: DetectedDeviceOut
  busy: string | null
  onPropose: (device: DetectedDeviceOut) => void
}): React.JSX.Element {
  const title = detectedTitle(device)
  return (
    <li
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 0',
        borderTop: '1px solid var(--bd)'
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, color: 'var(--tx)' }}>{title}</div>
        <div style={MONO_STYLE}>{detectedIdentity(device)}</div>
      </div>
      <div style={{ textAlign: 'right' }}>
        {device.ambiguous ? (
          <div style={MONO_STYLE}>pick this device explicitly on the Sources screen</div>
        ) : device.device_ref === null ? (
          <div style={MONO_STYLE}>no stable identity — replug to verify</div>
        ) : (
          <Button
            kind="soft"
            size="sm"
            aria-label={`Propose ${title}`}
            disabled={busy !== null}
            onClick={() => onPropose(device)}
          >
            {busy === device.device_ref ? <Spinner size={11} /> : 'Propose'}
          </Button>
        )}
      </div>
    </li>
  )
}

export function DetectedModal({
  projectId,
  mode,
  robots,
  onCreated,
  onClose
}: DetectedModalProps): React.JSX.Element {
  const [read, setRead] = useState<DeviceRead>({ phase: 'loading' })
  const [proposal, setProposal] = useState<ProposalOut | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [proposeError, setProposeError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    listDetectedDevices(projectId).then(
      (devices) => live && setRead({ phase: 'ready', devices }),
      (error: unknown) => live && setRead({ phase: 'error', message: hardwareErrorText(error) })
    )
    return () => {
      live = false
    }
  }, [projectId])

  const propose = async (device: DetectedDeviceOut): Promise<void> => {
    if (device.device_ref === null) return
    setBusy(device.device_ref)
    setProposeError(null)
    try {
      setProposal(await proposeDetected(projectId, device.device_ref))
    } catch (failure) {
      setProposeError(hardwareErrorText(failure))
    } finally {
      setBusy(null)
    }
  }

  return (
    <ModalShell onClose={onClose} width={640}>
      {proposal ? (
        <ProposalView
          projectId={projectId}
          proposal={proposal}
          robots={robots}
          mode={mode}
          onCreated={onCreated}
          onClose={onClose}
        />
      ) : (
        <>
          <div style={{ fontSize: 16, fontWeight: 600 }}>Detected devices</div>
          <div style={BODY_STYLE}>{HARDWARE_COPY.detected[mode]}</div>
          {read.phase === 'loading' && <p role="status">Looking for devices…</p>}
          {read.phase === 'error' && <p role="alert">{read.message}</p>}
          {read.phase === 'ready' && read.devices.length === 0 && (
            <p style={BODY_STYLE}>{HARDWARE_COPY.noDevices[mode]}</p>
          )}
          {read.phase === 'ready' && read.devices.length > 0 && (
            <ul
              aria-label="Detected devices"
              style={{ listStyle: 'none', margin: '12px 0 0', padding: 0 }}
            >
              {read.devices.map((device, index) => (
                <DeviceRowItem
                  key={device.device_ref ?? `${device.transport}-${index}`}
                  device={device}
                  busy={busy}
                  onPropose={(target) => void propose(target)}
                />
              ))}
            </ul>
          )}
          {proposeError && (
            <p role="alert" style={{ color: 'var(--err)', fontSize: 11.5 }}>
              {proposeError}
            </p>
          )}
          <CloseFooter onClose={onClose} />
        </>
      )}
    </ModalShell>
  )
}
