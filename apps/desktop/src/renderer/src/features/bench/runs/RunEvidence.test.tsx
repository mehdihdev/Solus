import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { RunEvidence } from './RunEvidence'
import { getRun, runFindings, compareRuns, type RunSummary, type RunManifest } from './runsApi'
vi.mock('./runsApi', () => ({ getRun: vi.fn(), runFindings: vi.fn(), compareRuns: vi.fn() }))
const run: RunSummary = {
  id: 'candidate',
  robot_id: 'r',
  session_id: null,
  name: 'Clamp 90',
  origin: 'recorded',
  status: 'truncated',
  started_at: '2026-01-01T00:00:00Z',
  ended_at: null,
  packet_count: 2,
  drop_count: 1,
  artifact_id: 'artifact'
}
const manifest: RunManifest = {
  schema_version: 1,
  robot_id: 'r',
  started_at: run.started_at,
  packets: [
    {
      device_id: 'servo',
      timestamp: '2026-01-01T00:00:00Z',
      values: { position: 80 },
      units: { position: 'deg' }
    },
    {
      device_id: 'servo',
      timestamp: '2026-01-01T00:00:01Z',
      values: { position: 90 },
      units: { position: 'deg' }
    }
  ],
  parts: [{ entity_id: 'part', name: 'Shoulder', device_id: 'servo' }],
  sensors: [
    { kind: 'camera', artifact_id: 'frame', device_id: 'cam', timestamp: '2026-01-01T00:00:01Z' }
  ],
  snapshots: []
}
beforeEach(() => {
  vi.mocked(getRun).mockResolvedValue({ summary: run, manifest })
  vi.mocked(runFindings).mockResolvedValue({
    findings: [],
    insufficient: [{ entity_id: 'part', reason: 'Measured current is missing.' }]
  })
  vi.mocked(compareRuns).mockResolvedValue({
    config_changes: [{ entity_id: 'part', field: 'position_max', before: 120, after: 90 }],
    source_snapshots_changed: true,
    divergences: [
      {
        device_id: 'servo',
        signal: 'position',
        aligned_samples: 2,
        max_difference: 30,
        unit: 'deg'
      }
    ],
    clamp_attributions: [
      {
        entity_id: 'part',
        explanation: 'Positions follow the changed upper bound.',
        before_limit: 120,
        after_limit: 90
      }
    ],
    insufficient: []
  })
})
it('scrubs exact recorded values and sensor references while retaining partial/unknown evidence', async () => {
  render(<RunEvidence projectId="p" run={run} runs={[run]} />)
  const slider = await screen.findByLabelText('Playback time')
  expect(screen.getByText(/partial recording/)).toBeInTheDocument()
  expect(screen.getByText(/Measured current is missing/)).toBeInTheDocument()
  expect(screen.getByText('80')).toBeInTheDocument()
  fireEvent.change(slider, { target: { value: '1' } })
  expect(screen.getByText('90')).toBeInTheDocument()
  expect(screen.queryByText('80')).not.toBeInTheDocument()
  expect(screen.getByText(/artifact frame/)).toBeInTheDocument()
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
})
it('compares an explicit same-robot pair and keeps attribution separate from divergence', async () => {
  const baseline = { ...run, id: 'baseline', name: 'Clamp 120', status: 'completed' as const }
  render(
    <RunEvidence
      projectId="p"
      run={run}
      runs={[baseline, run, { ...baseline, id: 'foreign-robot', robot_id: 'other', name: 'Other' }]}
    />
  )
  expect(screen.queryByRole('option', { name: /Other/ })).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Baseline run'), { target: { value: 'baseline' } })
  expect(await screen.findByText(/maximum difference 30 deg/)).toBeInTheDocument()
  expect(screen.getByText(/Positions follow the changed upper bound/)).toBeInTheDocument()
  expect(compareRuns).toHaveBeenCalledWith('p', 'baseline', 'candidate')
})
it('still opens playback when finding generation is unavailable', async () => {
  vi.mocked(runFindings).mockRejectedValue(new Error('unavailable'))
  render(<RunEvidence projectId="p" run={run} runs={[run]} />)
  await screen.findByLabelText('Playback time')
  expect(screen.getByText(/Findings could not be loaded/)).toBeInTheDocument()
  expect(screen.queryByText('No supported finding was produced.')).not.toBeInTheDocument()
})

it('renders the server finding with its accepted part, rating and captured code/CAD evidence', async () => {
  vi.mocked(runFindings).mockResolvedValue({
    findings: [
      {
        entity_id: 'part',
        headline: 'Possible stall at Shoulder',
        explanation: 'Current reached the captured rating while position remained still.',
        detail: 'The mechanical cause is unknown.',
        code_site: 'control.py:24',
        cad_revision: 'microversion-2',
        evidence: {
          stall_current_a: 1.5,
          measured_current_min_a: 1.6,
          configured_max: 90,
          position_unit: 'deg'
        }
      }
    ],
    insufficient: []
  })
  render(<RunEvidence projectId="p" run={run} runs={[run]} />)
  expect(
    await screen.findByRole('heading', { name: 'Possible stall at Shoulder' })
  ).toBeInTheDocument()
  fireEvent.click(screen.getByText('Evidence and context'))
  expect(screen.getByText('stall current a')).toBeInTheDocument()
  expect(screen.getByText('1.5')).toBeInTheDocument()
  expect(screen.getByText('Code: control.py:24')).toBeInTheDocument()
  expect(screen.getByText('CAD revision: microversion-2')).toBeInTheDocument()
})
