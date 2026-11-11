import { expect, it, vi } from 'vitest'
import { api } from '../../../lib/api/client'
import { compareRuns, getRun, importRun, listRuns, runFindings, startRun, stopRun } from './runsApi'
vi.mock('../../../lib/api/client', () => ({ api: { request: vi.fn() } }))
const id = '11111111-1111-4111-8111-111111111111'
const timestamp = '2026-01-01T00:00:00Z'
export const summary = {
  id,
  robot_id: id,
  session_id: null,
  name: 'Run',
  origin: 'synthetic',
  status: 'completed',
  started_at: timestamp,
  ended_at: timestamp,
  packet_count: 1,
  drop_count: 0,
  artifact_id: id
}
export const manifest = {
  schema_version: 1,
  robot_id: id,
  started_at: timestamp,
  packets: [
    {
      device_id: 'servo',
      timestamp,
      values: { position: 1 },
      units: { position: 'rad' },
      seq: 1,
      schema_version: 1
    }
  ],
  sensors: [],
  parts: [],
  snapshots: []
}
it.each([
  ['list rows', () => listRuns('p'), { runs: [{ ...summary, name: {} }], next_cursor: null }],
  [
    'baseline flag',
    () => listRuns('p'),
    { runs: [{ ...summary, baseline: 'yes' }], next_cursor: null }
  ],
  [
    'start',
    () => startRun('p', { robot_id: id, session_id: id, name: 'Run' }),
    { ...summary, packet_count: Infinity }
  ],
  ['stop', () => stopRun('p', id), { ...summary, drop_count: -1 }],
  [
    'import',
    () => importRun('p', { robot_id: id, artifact_id: id, name: 'Run', origin: 'synthetic' }),
    { ...summary, id: 'not-a-uuid' }
  ],
  ['detail', () => getRun('p', id), { summary, manifest: { ...manifest, packets: {} } }],
  [
    'findings',
    () => runFindings('p', id),
    {
      findings: [
        {
          entity_id: id,
          headline: {},
          explanation: 'x',
          detail: 'x',
          code_site: null,
          cad_revision: null,
          evidence: {}
        }
      ],
      insufficient: []
    }
  ],
  [
    'comparison',
    () => compareRuns('p', id, id),
    {
      config_changes: [],
      source_snapshots_changed: true,
      divergences: [
        {
          device_id: 'servo',
          signal: 'p',
          aligned_samples: 1,
          max_difference: Infinity,
          unit: 'rad'
        }
      ],
      clamp_attributions: [],
      insufficient: []
    }
  ]
] as const)('rejects malformed %s at the API boundary', async (_name, call, response) => {
  vi.mocked(api.request).mockResolvedValue(response)
  await expect(call()).rejects.toThrow(/Invalid run/)
})
it.each([
  { ...manifest, packets: [{ ...manifest.packets[0], values: { position: {} } }] },
  { ...manifest, packets: [{ ...manifest.packets[0], values: { position: NaN } }] },
  { ...manifest, packets: [{ ...manifest.packets[0], timestamp: '2026-02-31T00:00:00Z' }] },
  { ...manifest, packets: [{ ...manifest.packets[0], seq: Number.MAX_SAFE_INTEGER + 1 }] },
  { ...manifest, sensors: [{ artifact_id: id, timestamp, device_id: 'cam', kind: {} }] },
  { ...manifest, snapshots: [{ entity_id: id, kind: 'config', name: 'Config', data: {} }] },
  {
    ...manifest,
    parts: [{ entity_id: id, name: 'Servo', device_id: 'servo', stall_current_a: Infinity }]
  },
  { ...manifest, packets: Array(10001).fill(manifest.packets[0]) },
  { ...manifest, unexpected: true }
])('rejects malformed nested manifest %#', async (bad) => {
  vi.mocked(api.request).mockResolvedValue({ summary, manifest: bad })
  await expect(getRun('p', id)).rejects.toThrow(/Invalid run/)
})
it('accepts a bounded complete manifest and preserves original values', async () => {
  vi.mocked(api.request).mockResolvedValue({ summary, manifest })
  expect(await getRun('p', id)).toEqual({ summary, manifest })
})
it('keeps the baseline flag a list row and a detail summary carry', async () => {
  const marked = { ...summary, baseline: true }
  vi.mocked(api.request).mockResolvedValue({
    runs: [marked, { ...summary, baseline: false }],
    next_cursor: null
  })
  expect((await listRuns('p')).runs.map((run) => run.baseline)).toEqual([true, false])
  vi.mocked(api.request).mockResolvedValue({ summary: marked, manifest })
  expect((await getRun('p', id)).summary).toEqual(marked)
})
it('reads a simulated run (origin sim) and its pinned flag', async () => {
  const sim = { ...summary, origin: 'sim', pinned: true }
  vi.mocked(api.request).mockResolvedValue({ runs: [sim], next_cursor: null })
  expect((await listRuns('p')).runs[0]).toEqual(sim)
  vi.mocked(api.request).mockResolvedValue({ summary: sim, manifest })
  expect((await getRun('p', id)).summary).toEqual(sim)
  vi.mocked(api.request).mockResolvedValue({ runs: [{ ...summary, origin: 'dream' }], next_cursor: null })
  await expect(listRuns('p')).rejects.toThrow()
})
it('reads a summary without a baseline key, as start, import and a live stop send it', async () => {
  vi.mocked(api.request).mockResolvedValue(summary)
  const started = await startRun('p', { robot_id: id, session_id: id, name: 'Run' })
  expect(started).toEqual(summary)
  expect(started.baseline).toBeUndefined()
  vi.mocked(api.request).mockResolvedValue({ runs: [summary], next_cursor: null })
  expect((await listRuns('p')).runs[0].baseline).toBeUndefined()
})

it('rejects oversized lists, text and aggregate manifest data before rendering', async () => {
  for (const payload of [
    { runs: Array(51).fill(summary), next_cursor: null },
    { runs: [summary], next_cursor: 'x'.repeat(2049) },
    { runs: [{ ...summary, name: 'x'.repeat(121) }], next_cursor: null }
  ]) {
    vi.mocked(api.request).mockResolvedValue(payload)
    await expect(listRuns('p')).rejects.toThrow(/Invalid run/)
  }
  vi.mocked(api.request).mockResolvedValue({
    summary,
    manifest: {
      ...manifest,
      snapshots: Array.from({ length: 130 }, () => ({
        entity_id: id,
        kind: 'config',
        name: 'Snapshot',
        data: 'x'.repeat(65536)
      }))
    }
  })
  await expect(getRun('p', id)).rejects.toThrow(/Invalid run/)
})
it('rejects duplicate accepted parts and units naming absent signals', async () => {
  const part = { entity_id: id, name: 'Servo', device_id: 'servo' }
  for (const bad of [
    { ...manifest, parts: [part, part] },
    { ...manifest, packets: [{ ...manifest.packets[0], units: { absent: 'rad' } }] }
  ]) {
    vi.mocked(api.request).mockResolvedValue({ summary, manifest: bad })
    await expect(getRun('p', id)).rejects.toThrow(/Invalid run/)
  }
})

it('accepts actual deterministic findings and comparison evidence shapes', async () => {
  const evidence = {
    stall_current_a: 1.5,
    measured_current_min_a: 1.6,
    commanded_min: 2,
    commanded_max: 2,
    configured_min: null,
    configured_max: 1,
    position_unit: 'rad',
    samples: 3,
    window_start: timestamp,
    window_end: timestamp
  }
  const findings = {
    findings: [
      {
        entity_id: id,
        headline: 'Possible stall',
        explanation: 'Evidence',
        detail: 'Cause unknown',
        code_site: null,
        cad_revision: null,
        evidence
      }
    ],
    insufficient: []
  }
  vi.mocked(api.request).mockResolvedValue(findings)
  expect(await runFindings('p', id)).toEqual(findings)
  vi.mocked(api.request).mockResolvedValue({
    findings: [{ ...findings.findings[0], evidence: { ...evidence, samples: {} } }],
    insufficient: []
  })
  await expect(runFindings('p', id)).rejects.toThrow(/Invalid run/)
  const comparison = {
    config_changes: [{ entity_id: id, field: 'position_max', before: 2, after: 1 }],
    source_snapshots_changed: false,
    divergences: [
      { device_id: 'servo', signal: 'position', aligned_samples: 3, max_difference: 1, unit: 'rad' }
    ],
    clamp_attributions: [
      { entity_id: id, explanation: 'Changed bound', before_limit: 2, after_limit: 1 }
    ],
    insufficient: []
  }
  vi.mocked(api.request).mockResolvedValue(comparison)
  expect(await compareRuns('p', id, id)).toEqual(comparison)
})

it('reads the findings a run recorded and the finding deltas compare reports', async () => {
  const other = '22222222-2222-4222-8222-222222222222'
  const recorded = {
    finding_id: id,
    rule_id: 'tracking_error_stall',
    subjects: [id, other],
    severity: 'critical',
    count: 2,
    first_seen: timestamp,
    last_seen: '2026-01-01T00:00:09.250000Z'
  }
  vi.mocked(api.request).mockResolvedValue({
    summary,
    manifest: { ...manifest, findings: [recorded] }
  })
  expect((await getRun('p', id)).manifest.findings).toEqual([recorded])
  for (const bad of [
    { ...recorded, severity: 'fatal' },
    { ...recorded, count: 0 },
    { ...recorded, subjects: ['not-an-id'] },
    { ...recorded, headline: 'not recorded' }
  ]) {
    vi.mocked(api.request).mockResolvedValue({
      summary,
      manifest: { ...manifest, findings: [bad] }
    })
    await expect(getRun('p', id)).rejects.toThrow(/Invalid run/)
  }
  const comparison = {
    config_changes: [],
    source_snapshots_changed: false,
    divergences: [],
    clamp_attributions: [],
    insufficient: [],
    finding_deltas: [
      {
        rule_id: 'rail_sag_correlated',
        subjects: [id],
        change: 'new',
        severity: 'warning',
        baseline: null,
        candidate: { finding_id: other, count: 1 }
      },
      {
        rule_id: 'tracking_error_stall',
        subjects: [id, other],
        change: 'persisting',
        severity: 'critical',
        baseline: { finding_id: id, count: 3 },
        candidate: { finding_id: other, count: 5 }
      }
    ],
    expected_source: 'baseline_run'
  }
  vi.mocked(api.request).mockResolvedValue(comparison)
  expect(await compareRuns('p', id, id)).toEqual(comparison)
  for (const bad of [
    { ...comparison, expected_source: 'guess' },
    { ...comparison, finding_deltas: [{ ...comparison.finding_deltas[0], change: 'moved' }] },
    { ...comparison, finding_deltas: [{ ...comparison.finding_deltas[0], candidate: {} }] }
  ]) {
    vi.mocked(api.request).mockResolvedValue(bad)
    await expect(compareRuns('p', id, id)).rejects.toThrow(/Invalid run/)
  }
})
it('reads the evidence compare adds against a routine twin, and a comparison without it', async () => {
  const other = '22222222-2222-4222-8222-222222222222'
  const plain = {
    config_changes: [],
    source_snapshots_changed: false,
    divergences: [],
    clamp_attributions: [],
    insufficient: [],
    finding_deltas: [],
    expected_source: 'sim'
  }
  const evidence = {
    sim_result_id: id,
    real_passed: false,
    sim_passed: true,
    task_passed: false,
    sim_control: 'electrical_or_mechanical',
    reason: null,
    simulation_gap: true,
    residuals: {
      [id]: {
        status: 'attributed',
        parameter: 'mass',
        explained: { mass: 0.93, limit: 0.1, sensor_offset: 0.2, contact: 0.05 },
        estimate: {
          mass: { tau_s: 0.1 },
          limit: { side: 'upper', at: 45 },
          sensor_offset: { offset: 1.5 },
          contact: { at_s: 2 }
        },
        residual_rms: 0.3,
        samples: 256
      },
      [other]: { status: 'consistent', parameter: null, residual_rms: 0, samples: 256 }
    }
  }
  const unsaid = {
    ...evidence,
    real_passed: null,
    sim_control: null,
    reason: 'the real run states nothing that says whether it passed',
    simulation_gap: false,
    residuals: { [id]: { status: 'insufficient', parameter: null, reason: 'the run needs 8' } }
  }
  for (const comparison of [plain, { ...plain, evidence }, { ...plain, evidence: unsaid }]) {
    vi.mocked(api.request).mockResolvedValue(comparison)
    expect(await compareRuns('p', id, id)).toEqual(comparison)
  }
  for (const bad of [
    { ...evidence, sim_control: 'hardware' },
    { ...evidence, real_passed: 'no' },
    { ...evidence, unexpected: true },
    { ...evidence, residuals: { [id]: { status: 'guessed', parameter: null } } },
    { ...evidence, residuals: { 'not-an-id': evidence.residuals[id] } },
    { ...evidence, residuals: { [id]: { ...evidence.residuals[id], parameter: 'friction' } } }
  ]) {
    vi.mocked(api.request).mockResolvedValue({ ...plain, evidence: bad })
    await expect(compareRuns('p', id, id)).rejects.toThrow(/Invalid run/)
  }
})
