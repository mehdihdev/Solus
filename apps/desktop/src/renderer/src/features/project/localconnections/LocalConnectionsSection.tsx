// The Local Connections section of the Sources screen (SOLUSDEV-72): how a
// project starts LOCAL streams — simulators, serial devices, and bridge-backed
// local tools. Everything renders from live backend claims; offline degrades
// to honest copy, never fabricated availability. Active sessions appear inline
// with their source rows; sessions matching no row stay listed and stoppable.
import { Card } from '../../../components/ui/Card'
import { Mono } from '../../../components/ui/Mono'
import {
  createBenchSession,
  stopBenchSession,
  type BenchSources,
  type BenchSession,
  type CreateBenchSessionInput
} from '../../../lib/api/resources'
import { useBridgeStatus } from '../../workspace/useBridgeStatus'
import { DeviceRow } from './DeviceRow'
import { LocalToolRows } from './LocalToolRows'
import { SessionChip } from './SessionChip'
import { SimulatorRow } from './SimulatorRow'
import { useLocalConnections, useLocalTools } from './useLocalConnections'
import {
  connectErrorText,
  sessionsForDevice,
  sessionsForSimulator,
  unmatchedSessions
} from './presentation'

function SubLabel({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div style={{ margin: '24px 0 10px' }}>
      <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
        {children}
      </Mono>
    </div>
  )
}

/** Simulator + device rows for live bench sources. */
function BenchRows({
  sources,
  sessions,
  onStart,
  onStop
}: {
  sources: BenchSources
  sessions: BenchSession[]
  onStart: (input: CreateBenchSessionInput) => Promise<string | null>
  onStop: (sessionId: string) => void
}): React.JSX.Element {
  // Runner missing ⇒ livebench isn't installed server-side: every control
  // below is disabled with that exact reason.
  const runnerReason = sources.runner.available
    ? null
    : (sources.runner.reason ?? 'livebench is not available on the server')
  const orphans = unmatchedSessions(sessions, sources.simulators, sources.devices)

  return (
    <>
      <SubLabel>SIMULATORS</SubLabel>
      <Card pad={16}>
        {sources.simulators.map((sim) => (
          <SimulatorRow
            key={sim.kind}
            simulator={sim}
            sessions={sessionsForSimulator(sessions, sim.kind)}
            disabledReason={runnerReason}
            onStart={(config) => onStart({ mode: 'sim', config })}
            onStop={onStop}
          />
        ))}
      </Card>
      <SubLabel>DEVICES</SubLabel>
      <Card pad={16}>
        {sources.devices.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--mut)' }}>No serial devices detected.</div>
        ) : (
          sources.devices.map((device) => (
            <DeviceRow
              key={`${device.device_path}:${device.serial_number ?? ''}`}
              device={device}
              sessions={sessionsForDevice(sessions, device)}
              disabledReason={runnerReason}
              onConnect={(config) => onStart({ mode: 'real', config })}
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
      </Card>
    </>
  )
}

export function LocalConnectionsSection({ projectId }: { projectId: string }): React.JSX.Element {
  const { data, refresh } = useLocalConnections(projectId)
  const bridge = useBridgeStatus(projectId)
  const tools = useLocalTools()

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
    <>
      <SubLabel>LOCAL CONNECTIONS</SubLabel>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginBottom: 4 }}>
        Streams that start here on this machine — simulators, serial devices, and local tools
        bridged by the Solus companion.
      </div>
      {data === null ? (
        <Card pad={16} style={{ marginTop: 10 }}>
          <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
            Solus can&apos;t reach its API right now — local bench sources and devices will list
            here once the backend is reachable.
          </div>
        </Card>
      ) : (
        <BenchRows sources={data.sources} sessions={data.sessions} onStart={start} onStop={stop} />
      )}
      <SubLabel>LOCAL TOOLS (BRIDGE)</SubLabel>
      <Card pad={16}>
        <LocalToolRows tools={tools} bridge={bridge} />
      </Card>
    </>
  )
}
