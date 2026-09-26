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
