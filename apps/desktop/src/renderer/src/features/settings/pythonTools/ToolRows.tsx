// SOLUSDEV-329 — the per-tool rows of Settings › Python for local tools:
// live progress while a run is going, the last run's result (failed tools
// show the CLI's redacted message as TEXT plus a fix hint), else the
// companion's status. Never renders markup from the CLI.
import type { ForkResult, ForkStatus, ProgressEvent } from '../../../../../main/mcpRuntime/protocol'
import { StatusTag } from '../settingsUi'
import type { RunView } from './pythonToolsRun'
import { fixHint, forkName, stepLabel, unsupportedPlatform } from './pythonToolsCopy'

export interface ToolRowsProps {
  forks: readonly ForkStatus[]
  run: RunView | null
  running: boolean
  needsSetup: readonly string[]
}

function RowState({
  fork,
  progress,
  result,
  needsSetup
}: {
  fork: ForkStatus
  progress: ProgressEvent | undefined
  result: ForkResult | undefined
  needsSetup: boolean
}): React.JSX.Element {
  if (progress)
    return <span style={MUTED}>{stepLabel(progress.step, progress.done, progress.total)}</span>
  if (fork.state === 'unsupported_platform')
    return <span style={MUTED}>{unsupportedPlatform(fork.fork)}</span>
  if (result?.outcome === 'failed') {
    return (
      <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <StatusTag tone="err">Failed</StatusTag>
        {result.message && <span style={MUTED}>{result.message}</span>}
        <span style={MUTED}>{fixHint(result.error_code)}</span>
      </span>
    )
  }
  if (needsSetup && result?.outcome !== 'ok') return <StatusTag tone="warn">Needs setup</StatusTag>
  const version = fork.base_version ? ` · ${fork.base_version}` : ''
  return <StatusTag tone="ok">{`✓ Ready${version}`}</StatusTag>
}

export function ToolRows({ forks, run, running, needsSetup }: ToolRowsProps): React.JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {forks.map((f) => (
        <div key={f.fork} data-testid={`python-fork-${f.fork}`} style={ROW}>
          <span style={{ minWidth: 70, fontSize: 12.5 }}>{forkName(f.fork)}</span>
          <RowState
            fork={f}
            progress={running ? run?.progress[f.fork] : undefined}
            result={run?.results.find((r) => r.fork === f.fork)}
            needsSetup={needsSetup.includes(f.fork)}
          />
        </div>
      ))}
    </div>
  )
}

const ROW: React.CSSProperties = { display: 'flex', alignItems: 'flex-start', gap: 12 }
const MUTED: React.CSSProperties = { color: 'var(--mut)', fontSize: 11.5 }
