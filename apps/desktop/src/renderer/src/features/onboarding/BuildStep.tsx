// Onboarding step 6 — the context-model build view (graph panel: SOLUSDEV-323). De-simulated in
// SOLUSDEV-152: the log shows REAL per-source sync state (via buildProgress /
// the SOLUSDEV-100 sync helpers) and the summary shows the real entity count
// from the graph. When the workspace never linked (offline/dev bypass) the
// step completes with an honest empty state — nothing is ever fabricated.
import { useEffect } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { Mono } from '../../components/ui/Mono'
import { BuildGraph } from './BuildGraph'
import { getSyncs, listEntities, listSources } from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useOnboardingStore, type BuildLine } from './onboardingStore'
import { runBuildProgress, type BuildProgressApi } from './buildProgress'

/** The typed API surface the progress reader runs against (app singleton). */
const buildApi: BuildProgressApi = { listSources, getSyncs, listEntities }

interface BuildStepProps {
  onComplete: () => void
}

export function BuildStep({ onComplete }: BuildStepProps): React.JSX.Element {
  const buildLog = useOnboardingStore((s) => s.buildLog)
  const buildDone = useOnboardingStore((s) => s.buildDone)
  const buildEntityCount = useOnboardingStore((s) => s.buildEntityCount)
  const setBuildLog = useOnboardingStore((s) => s.setBuildLog)
  const finishBuild = useOnboardingStore((s) => s.finishBuild)
  const resetBuild = useOnboardingStore((s) => s.resetBuild)
  const linked = useWorkspaceStore((s) => s.linked)
  const projectId = useWorkspaceStore((s) => s.project?.id)

  // Every effect run restarts the REAL progress read (StrictMode-safe: stale
  // runs are cancelled and their results dropped). An unlinked workspace has
  // nothing to read — the step completes immediately and honestly empty.
  useEffect(() => {
    let cancelled = false
    resetBuild()
    if (!linked || !projectId) {
      finishBuild()
      return
    }
    void runBuildProgress(
      {
        api: buildApi,
        onLines: (lines) => {
          if (!cancelled) setBuildLog(lines)
        }
      },
      projectId
    ).then((progress) => {
      if (cancelled) return
      setBuildLog(progress.lines)
      finishBuild(progress.entityCount)
    })
    return () => {
      cancelled = true
    }
  }, [linked, projectId, resetBuild, setBuildLog, finishBuild])

  return (
    <div style={{ display: 'flex', gap: 28, flex: 1, minHeight: 0 }}>
      <BuildGraph lines={buildLog} />
      <div style={{ width: 320, flex: 'none', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <p
          className="ob-rise ob-d2"
          style={{ margin: 0, color: 'var(--mut)', fontSize: 13, lineHeight: 1.55 }}
        >
          {summaryFor(buildDone, buildLog, buildEntityCount)}
        </p>
        {buildLog.length > 0 && (
          <Card pad={0} className="ob-rise ob-d3" style={{ fontFamily: 'var(--font-mono)' }}>
            {buildLog.map((line, i) => (
              <BuildLogRow key={`${line.name}-${i}`} line={line} />
            ))}
          </Card>
        )}
        {!buildDone && (
          <div
            style={{
              display: 'flex',
              gap: 10,
              fontSize: 11,
              fontFamily: 'var(--font-mono)',
              color: 'var(--acc)',
              alignItems: 'center'
            }}
          >
            <Spinner size={11} /> reading sync progress…
          </div>
        )}
        {buildDone && <FinishCard onComplete={onComplete} />}
      </div>
    </div>
  )
}

function FinishCard({ onComplete }: { onComplete: () => void }): React.JSX.Element {
  return (
    <div className="ob-rise" style={{ marginTop: 'auto' }}>
      <Card pad={0} style={{ borderColor: 'color-mix(in srgb, var(--acc) 35%, var(--bd))' }}>
        <div style={{ padding: '14px 16px' }}>
          <Mono size={9} color="var(--acc)">
            FIRST THING TO TRY
          </Mono>
          <div style={{ fontSize: 13, lineHeight: 1.55, marginTop: 6 }}>
            Open the tool you’re working in, double-tap{' '}
            <kbd className="ob-key" style={KBD}>
              ctrl
            </kbd>{' '}
            and ask me what you’re looking at.
          </div>
        </div>
      </Card>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
        <Button kind="primary" size="lg" onClick={onComplete}>
          Open workspace <Icons.arrowR size={14} />
        </Button>
      </div>
    </div>
  )
}

const KBD = {
  minWidth: 0,
  height: 20,
  padding: '0 6px',
  fontSize: 10,
  boxShadow: '0 2px 0 var(--bd)'
} as const

/** Honest summary line: the real graph count, or the real absence of one. */
function summaryFor(
  buildDone: boolean,
  buildLog: readonly BuildLine[],
  entityCount: number | null
): string {
  if (!buildDone) return 'Reading real sync progress from your connected sources…'
  if (entityCount !== null)
    return `${entityCount} entities in your graph, from your synced sources.`
  if (buildLog.length > 0) return 'Sync results above — connect more tools anytime from Sources.'
  return 'No sources are syncing yet — you can connect tools anytime from your workspace.'
}

function BuildLogRow({ line }: { line: BuildLine }): React.JSX.Element {
  return (
    <div
      className="ob-logline"
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        gap: 16,
        padding: '9px 16px',
        borderBottom: '1px solid var(--bd)',
        fontSize: 11
      }}
    >
      <span style={{ color: 'var(--tx)', display: 'inline-flex', alignItems: 'center', gap: 10 }}>
        <LineIndicator state={line.state} />
        {line.name}
      </span>
      <span
        className={line.state === 'pending' ? 'ob-sheen' : undefined}
        style={{
          color: line.state === 'pending' ? undefined : lineDetailColor(line.state),
          textAlign: 'right'
        }}
      >
        {line.detail}
      </span>
    </div>
  )
}

function LineIndicator({ state }: { state: BuildLine['state'] }): React.JSX.Element {
  if (state === 'pending') return <Spinner size={11} />
  if (state === 'failed')
    return (
      <span style={{ color: 'var(--err)' }}>
        <Icons.warn size={12} />
      </span>
    )
  if (state === 'idle') return <span style={{ color: 'var(--mut)' }}>–</span>
  return (
    <span style={{ color: 'var(--ok)' }}>
      <Icons.check size={12} />
    </span>
  )
}

function lineDetailColor(state: BuildLine['state']): string {
  return state === 'failed' ? 'var(--err)' : 'var(--mut)'
}
