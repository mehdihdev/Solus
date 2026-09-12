// The Simulation tab of Home's connected-accounts card (SOLUSDEV-244), in the
// same shape as every other tab: one row per simulator the machine can run —
// mark, name, the backend's own availability — with Start as the next step
// (SimulatorStartModal), and the running sessions beneath, each with Stop.
// The inventory is the OPEN project's `GET /projects/{id}/bench/sources`; a
// start is `POST …/bench/sessions` on that project — the same calls the
// retired per-project source list made. No open project means nothing can honestly start, and
// the panel says so; an unreachable API says that, never a fabricated list.
import { useState } from 'react'
import {
  createBenchSession,
  stopBenchSession,
  type BenchSession,
  type BenchSimulator,
  type CreateBenchSessionInput
} from '../../lib/api/resources'
import type { WorkspaceProject } from '../../store/workspaceStore'
import { SessionChip } from '../project/localconnections/SessionChip'
import {
  connectErrorText,
  sessionsForSimulator,
  simulatorMark,
  simulatorName,
  type SimStartConfig
} from '../project/localconnections/presentation'
import { useLocalConnections } from '../project/localconnections/useLocalConnections'
import { ToolRowHead } from './ConnectedAccountsCard'
import { SimulatorStartModal } from './SimulatorStartModal'

function Note({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div style={{ padding: 14, fontSize: 11.5, color: 'var(--mut)', lineHeight: 1.5 }}>
      {children}
    </div>
  )
}

function SimulatorToolRow({
  simulator,
  sessions,
  projectName,
  runnerReason,
  onStart,
  onStop
}: {
  simulator: BenchSimulator
  sessions: BenchSession[]
  projectName: string
  runnerReason: string | null
  onStart: (config: SimStartConfig) => Promise<string | null>
  onStop: (sessionId: string) => void
}): React.JSX.Element {
  const [starting, setStarting] = useState(false)
  const name = simulatorName(simulator.kind)
  // Runner missing beats the simulator's own reason; Isaac has no in-app
  // start at all — none of these may offer a Start that cannot perform.
  const reason =
    runnerReason ??
    (simulator.available ? null : simulator.reason) ??
    (simulator.kind === 'isaac' ? 'No in-app start — use a script or an MCAP recording.' : null)
  const running = sessions.length
  const status = reason
    ? 'Unavailable on this machine'
    : running > 0
      ? `Ready · ${running} session${running === 1 ? '' : 's'} running in ${projectName}`
      : `Ready on this machine · runs in ${projectName}`
  return (
    <div>
      <ToolRowHead
        entry={{ id: simulator.kind, name, mark: simulatorMark(simulator.kind) }}
        status={status}
        action="Start"
        disabledHint={reason}
        onAction={() => setStarting(true)}
      />
      {sessions.map((session) => (
        <div
          key={session.id}
          style={{ padding: '0 16px 10px 56px', borderTop: '1px solid var(--bd)' }}
        >
          <SessionChip session={session} onStop={onStop} />
        </div>
      ))}
      {starting && (
        <SimulatorStartModal
          simulator={simulator}
          projectName={projectName}
          onStart={onStart}
          onClose={() => setStarting(false)}
        />
      )}
    </div>
  )
}

export function SimulationPanel({
  currentProject
}: {
  currentProject: WorkspaceProject | null
}): React.JSX.Element {
  const projectId = currentProject?.id ?? null
  const { data, refresh } = useLocalConnections(projectId)

  const start = async (input: CreateBenchSessionInput): Promise<string | null> => {
    if (!projectId) return 'Open a project first.'
    try {
      await createBenchSession(projectId, input)
      refresh()
      return null
    } catch (error) {
      return connectErrorText(error)
    }
  }

  const stop = (sessionId: string): void => {
    if (!projectId) return
    // Stop is idempotent server-side; the refresh shows whatever is true now.
    void stopBenchSession(projectId, sessionId)
      .catch(() => undefined)
      .then(refresh)
  }

  if (!currentProject) {
    return (
      <Note>
        Open a project to run a simulation — sessions stream into that project&apos;s Live Bench.
      </Note>
    )
  }
  if (data === null) {
    return (
      <Note>
        Solus can&apos;t reach its API right now — the simulators this machine can run will list
        here once the backend is reachable.
      </Note>
    )
  }
  // Runner missing ⇒ livebench isn't installed server-side: every Start is
  // disabled with that exact reason.
  const runnerReason = data.sources.runner.available
    ? null
    : (data.sources.runner.reason ?? 'livebench is not available on the server')
  const simulators = data.sources.simulators
  return (
    <>
      {simulators.map((sim, i) => (
        <div
          key={sim.kind}
          style={{ borderBottom: i === simulators.length - 1 ? 'none' : '1px solid var(--bd)' }}
        >
          <SimulatorToolRow
            simulator={sim}
            sessions={sessionsForSimulator(data.sessions, sim.kind)}
            projectName={currentProject.name}
            runnerReason={runnerReason}
            onStart={(config) => start({ mode: 'sim', config })}
            onStop={stop}
          />
        </div>
      ))}
    </>
  )
}
