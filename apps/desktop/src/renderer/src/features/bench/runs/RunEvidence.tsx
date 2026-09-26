import { useEffect, useState } from 'react'
import { useSettingsStore } from '../../../store/settingsStore'
import { Button } from '../../../components/ui/Button'
import { fetchArtifactBlob } from '../../sol/solApi'
import { workspaceSessionGeneration } from '../../graph/workspaceSession'
import {
  getRun,
  runFindings,
  compareRuns,
  type RunSummary,
  type RunDetail,
  type RunFindings,
  type RunComparison
} from './runsApi'
import { RunPlayback } from './RunPlayback'
import { RunNarrationPanel } from './RunNarrationPanel'

export function RunEvidence({
  projectId,
  run,
  runs
}: {
  projectId: string
  run: RunSummary
  runs: RunSummary[]
}): React.JSX.Element {
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [findings, setFindings] = useState<RunFindings | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const [baseline, setBaseline] = useState('')
  const [downloadError, setDownloadError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    let live = true
    void Promise.allSettled([
      getRun(projectId, run.id, controller.signal),
      runFindings(projectId, run.id, controller.signal)
    ]).then(([recording, evidence]) => {
      if (!live) return
      const failures: string[] = []
      if (recording.status === 'fulfilled') setDetail(recording.value)
      else failures.push('The retained manifest could not be loaded.')
      if (evidence.status === 'fulfilled') setFindings(evidence.value)
      else failures.push('Findings could not be loaded; no result is being inferred.')
      setErrors(failures)
    })
    return () => {
      live = false
      controller.abort()
    }
  }, [projectId, run.id])
  const download = async (): Promise<void> => {
    if (!run.artifact_id) return
    const generation = workspaceSessionGeneration()
    try {
      const blob = await fetchArtifactBlob(projectId, run.artifact_id)
      if (generation !== workspaceSessionGeneration()) return
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'recording.bench-run.json'
      anchor.click()
      URL.revokeObjectURL(url)
    } catch {
      if (generation === workspaceSessionGeneration())
        setDownloadError('The retained artifact could not be downloaded.')
    }
  }
  return (
    <section aria-label={`Recording ${run.name}`}>
      <h3>{run.name}</h3>
      <RecordingStatus run={run} />
      {run.artifact_id ? (
        <Button onClick={() => void download()}>Download retained manifest</Button>
      ) : (
        <p>A final artifact has not been filed yet.</p>
      )}
      {downloadError && <p role="alert">{downloadError}</p>}
      {errors.map((error) => (
        <p role="alert" key={error}>
          {error}
        </p>
      ))}
      {!detail && !errors.length && <p role="status">Loading recorded evidence…</p>}
      {detail && <RunPlayback projectId={projectId} manifest={detail.manifest} />}
      <Findings projectId={projectId} runId={run.id} findings={findings} />
      <CapturedSnapshots detail={detail} />
      <label>
        Baseline run{' '}
        <select value={baseline} onChange={(event) => setBaseline(event.target.value)}>
          <option value="">Choose a baseline</option>
          {runs
            .filter(
              (item) =>
                item.id !== run.id && item.robot_id === run.robot_id && item.status !== 'running'
            )
            .map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} · {item.origin} · {item.status}
              </option>
            ))}
        </select>
      </label>
      {baseline && (
        <RunComparisonPanel
          key={`${run.id}:${baseline}`}
          projectId={projectId}
          baselineId={baseline}
          candidateId={run.id}
        />
      )}
    </section>
  )
}
function RunComparisonPanel({
  projectId,
  baselineId,
  candidateId
}: {
  projectId: string
  baselineId: string
  candidateId: string
}): React.JSX.Element {
  const [result, setResult] = useState<RunComparison | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let live = true
    void compareRuns(projectId, baselineId, candidateId).then(
      (value) => {
        if (live) setResult(value)
      },
      () => {
        if (live) setError('These runs could not be compared.')
      }
    )
    return () => {
      live = false
    }
  }, [projectId, baselineId, candidateId])
  if (error) return <p role="alert">{error}</p>
  if (!result) return <p role="status">Comparing aligned recordings…</p>
  return (
    <section aria-label="Run comparison">
      <h3>Comparison</h3>
      <p>
        {result.source_snapshots_changed
          ? 'Captured source/configuration snapshots differ.'
          : 'Captured source/configuration snapshots match.'}
      </p>
      {!result.divergences.length && <p>No aligned signal divergence was established.</p>}
      {result.divergences.map((item) => (
        <p key={`${item.device_id}:${item.signal}`}>
          {item.device_id} · {item.signal}: maximum difference {item.max_difference}{' '}
          {item.unit ?? '(unit unknown)'} across {item.aligned_samples} aligned samples.
        </p>
      ))}
      {result.config_changes.map((item, index) => (
        <p key={index}>
          {item.entity_id} · {item.field}: {item.before ?? 'Unknown'} → {item.after ?? 'Unknown'}
        </p>
      ))}
      {result.clamp_attributions.map((item, index) => (
        <p key={index}>
          {item.entity_id}: {item.explanation} ({item.before_limit} → {item.after_limit})
        </p>
      ))}
      {result.insufficient.map((item, index) => (
        <p key={index}>
          {item.device_id} · {item.signal}: {item.reason}
        </p>
      ))}
    </section>
  )
}

function Findings({
  projectId,
  runId,
  findings
}: {
  projectId: string
  runId: string
  findings: RunFindings | null
}): React.JSX.Element {
  const mode = useSettingsStore((state) => state.solMode)
  return (
    <>
      {' '}
      {findings && (
        <section aria-label="Run findings">
          <h3>Findings</h3>
          <RunNarrationPanel projectId={projectId} runId={runId} />
          {!findings.findings.length && <p>No supported finding was produced.</p>}
          {findings.findings.map((finding, index) => (
            <article key={`${finding.entity_id}:${index}`}>
              <h4>{finding.headline}</h4>
              {mode === 'Guide' && <p>{finding.explanation}</p>}
              <details>
                <summary>Evidence and context</summary>
                {mode !== 'Guide' && <p>{finding.explanation}</p>}
                <p>{finding.detail}</p>
                <p>Part entity: {finding.entity_id}</p>
                <dl>
                  {Object.entries(finding.evidence).map(([key, value]) => (
                    <div key={key}>
                      <dt>{key.replaceAll('_', ' ')}</dt>
                      <dd>{value ?? 'Unknown'}</dd>
                    </div>
                  ))}
                </dl>
                <p>Code: {finding.code_site ?? 'Not captured'}</p>
                <p>CAD revision: {finding.cad_revision ?? 'Not captured'}</p>
              </details>
            </article>
          ))}
          {findings.insufficient.map((item, index) => (
            <p key={`${item.entity_id}:${index}`}>
              Insufficient evidence{item.entity_id ? ` for ${item.entity_id}` : ''}: {item.reason}
            </p>
          ))}
        </section>
      )}
    </>
  )
}

function CapturedSnapshots({ detail }: { detail: RunDetail | null }): React.JSX.Element {
  return (
    <>
      {' '}
      {detail && (
        <details>
          <summary>Captured configuration and revisions</summary>
          {detail.manifest.snapshots.length ? (
            detail.manifest.snapshots.map((snapshot) => (
              <div key={snapshot.entity_id}>
                <strong>{snapshot.name}</strong> · {snapshot.kind} ·{' '}
                {snapshot.revision ?? 'Revision unknown'}
                {snapshot.data && <pre style={{ whiteSpace: 'pre-wrap' }}>{snapshot.data}</pre>}
              </div>
            ))
          ) : (
            <p>No configuration or source revision snapshots were captured.</p>
          )}
        </details>
      )}
    </>
  )
}

function RecordingStatus({ run }: { run: RunSummary }): React.JSX.Element {
  return (
    <>
      {' '}
      <p>
        {run.origin === 'live' ? 'Live capture' : `User-declared ${run.origin} recording`} ·{' '}
        {run.status} · {run.packet_count} packets · {run.drop_count} dropped
      </p>
      {run.status === 'running' && (
        <p>
          Capture is running. Playback shows the loaded persisted checkpoint; stop the run to load
          the final manifest.
        </p>
      )}
      {run.status === 'interrupted' && (
        <p>The process was interrupted. Only persisted checkpoint samples are available.</p>
      )}
      {run.status === 'truncated' && (
        <p>The capture reached its bound. This is a partial recording.</p>
      )}
    </>
  )
}
