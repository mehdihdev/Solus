// The Simulation tab of Home's connected-accounts card (SOLUSDEV-244). The
// simulators a machine can run are a BENCH inventory, not an account grant:
// they come from the open project's `GET /projects/{id}/bench/sources`, and a
// start is `POST …/bench/sessions` on that project — the same rows and the
// same calls the project's Sources page makes, so nothing here is a second
// implementation. No open project means nothing can honestly start, and the
// panel says so; an unreachable API says that, never a fabricated inventory.
import {
  createBenchSession,
  stopBenchSession,
  type CreateBenchSessionInput
} from '../../lib/api/resources'
import type { WorkspaceProject } from '../../store/workspaceStore'
import { SimulatorRow } from '../project/localconnections/SimulatorRow'
import { connectErrorText, sessionsForSimulator } from '../project/localconnections/presentation'
import { useLocalConnections } from '../project/localconnections/useLocalConnections'

function Note({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div style={{ padding: 14, fontSize: 11.5, color: 'var(--mut)', lineHeight: 1.5 }}>
      {children}
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
  // Runner missing ⇒ livebench isn't installed server-side: every control is
  // disabled with that exact reason.
  const runnerReason = data.sources.runner.available
    ? null
    : (data.sources.runner.reason ?? 'livebench is not available on the server')
  return (
    <div style={{ padding: '0 14px' }}>
      <div style={{ fontSize: 10.5, color: 'var(--mut)', padding: '10px 0 0' }}>
        Runs in {currentProject.name}
      </div>
      {data.sources.simulators.map((sim) => (
        <SimulatorRow
          key={sim.kind}
          simulator={sim}
          sessions={sessionsForSimulator(data.sessions, sim.kind)}
          disabledReason={runnerReason}
          onStart={(config) => start({ mode: 'sim', config })}
          onStop={stop}
        />
      ))}
    </div>
  )
}
