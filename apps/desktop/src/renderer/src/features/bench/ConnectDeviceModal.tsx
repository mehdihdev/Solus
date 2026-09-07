// "Connect a device" on Live Bench (SOLUSDEV-244; the flow lived on the
// retired Sources page, SOLUSDEV-72): every USB-serial device the backend
// enumerated for THIS machine, with exactly what recognition claims, a real
// Connect that starts a serial session on the open project, and the running
// sessions with Stop. Offline / runner-absent degrade to honest copy with dead
// controls — never fabricated availability.
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import {
  createBenchSession,
  stopBenchSession,
  type CreateBenchSessionInput
} from '../../lib/api/resources'
import { DeviceRow } from '../project/localconnections/DeviceRow'
import { SessionChip } from '../project/localconnections/SessionChip'
import {
  connectErrorText,
  sessionsForDevice,
  unmatchedSessions
} from '../project/localconnections/presentation'
import { useLocalConnections } from '../project/localconnections/useLocalConnections'
import { ModalShell } from '../workspace/modals'

export function ConnectDeviceModal({
  projectId,
  onClose
}: {
  projectId: string
  onClose: () => void
}): React.JSX.Element {
  const { data, refresh } = useLocalConnections(projectId)

  const start = async (input: CreateBenchSessionInput): Promise<string | null> => {
    try {
      await createBenchSession(projectId, input)
      refresh()
      return null
    } catch (error) {
      return connectErrorText(error)
    }
  }
  const stop = (sessionId: string): void => {
    // Stop is idempotent server-side; the refresh shows whatever is true now.
    void stopBenchSession(projectId, sessionId)
      .catch(() => undefined)
      .then(refresh)
  }

  return (
    <ModalShell onClose={onClose} width={640}>
      <div role="dialog" aria-modal="true" aria-label="Connect a device">
        <div style={{ fontSize: 16, fontWeight: 600 }}>Connect a device</div>
        <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 4, lineHeight: 1.5 }}>
          USB-serial devices on this computer. The serial number is what Solus binds to, so a
          reconnect reopens the same physical device.
        </div>
        <div style={{ marginTop: 14 }}>
          {data === null ? (
            <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
              Solus can&apos;t reach its API right now — devices will list here once the backend is
              reachable.
            </div>
          ) : (
            <Devices data={data} onConnect={start} onStop={stop} />
          )}
        </div>
        <div style={{ display: 'flex', marginTop: 18, justifyContent: 'flex-end' }}>
          <Button kind="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </ModalShell>
  )
}

function Devices({
  data,
  onConnect,
  onStop
}: {
  data: NonNullable<ReturnType<typeof useLocalConnections>['data']>
  onConnect: (input: CreateBenchSessionInput) => Promise<string | null>
  onStop: (sessionId: string) => void
}): React.JSX.Element {
  // Runner missing ⇒ livebench isn't installed server-side: every control is
  // disabled with that exact reason.
  const runnerReason = data.sources.runner.available
    ? null
    : (data.sources.runner.reason ?? 'livebench is not available on the server')
  const orphans = unmatchedSessions(data.sessions, data.sources.simulators, data.sources.devices)
  return (
    <>
      {data.sources.devices.length === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--mut)' }}>No serial devices detected.</div>
      ) : (
        data.sources.devices.map((device) => (
          <DeviceRow
            key={`${device.device_path}:${device.serial_number ?? ''}`}
            device={device}
            sessions={sessionsForDevice(data.sessions, device)}
            disabledReason={runnerReason}
            onConnect={(config) => onConnect({ mode: 'real', config })}
            onStop={onStop}
          />
        ))
      )}
      {orphans.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <Mono size={8.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
            OTHER ACTIVE SESSIONS
          </Mono>
          {orphans.map((session) => (
            <SessionChip key={session.id} session={session} onStop={onStop} />
          ))}
        </div>
      )}
    </>
  )
}
