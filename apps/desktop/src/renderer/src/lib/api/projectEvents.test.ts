import { expect, it, vi } from 'vitest'
import type { DetectedDeviceOut } from './hardware'
import { streamProjectEvents, toDetectedDevices, type ProjectEvent } from './projectEvents'
import {
  PROJECT_ID,
  graphChanged,
  jobUpdated,
  layoutChanged,
  projectAccessRevoked,
  projectReady,
  projectUpdated,
  sourcesChanged,
  sse,
  teamUpdated
} from './liveStreamFixtures'
import { LiveStreamHttpError } from './liveStream'

function response(chunks: string[]): Response {
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk))
        controller.close()
      }
    })
  )
}
async function collect(fetchImpl: typeof fetch, signal?: AbortSignal): Promise<ProjectEvent[]> {
  const events: ProjectEvent[] = []
  for await (const event of streamProjectEvents({
    projectId: 'p1',
    baseUrl: 'https://api.test',
    getToken: () => 'test-session',
    fetchImpl,
    signal
  }))
    events.push(event)
  return events
}
it('authenticates once and accepts only complete events for the selected project', async () => {
  const fetchImpl = vi
    .fn()
    .mockResolvedValue(
      response([
        'event: ready\ndata: {"project_',
        'id":"p1"}\n\nevent: graph.changed\ndata: {"project_id":"foreign"}\n\n',
        ': keepalive\n\nevent: graph.changed\ndata: broken\n\n',
        'event: unknown\ndata: {"project_id":"p1"}\n\n',
        'event: graph.changed\ndata: {"project_id":"p1"}\n\n'
      ])
    )
  expect(await collect(fetchImpl)).toEqual(['ready', 'graph.changed'])
  expect(fetchImpl).toHaveBeenCalledWith(
    'https://api.test/projects/p1/events',
    expect.objectContaining({
      method: 'GET',
      headers: { Accept: 'text/event-stream', Authorization: 'Bearer test-session' }
    })
  )
})
it('retains authorization status for reconnect policy', async () => {
  await expect(
    collect(vi.fn().mockResolvedValue(new Response(null, { status: 403 })))
  ).rejects.toMatchObject({ status: 403 })
})
it('bounds incomplete frames and cancels their reader', async () => {
  const cancel = vi.fn()
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('x'.repeat(70_000)))
    },
    cancel
  })
  await expect(collect(vi.fn().mockResolvedValue(new Response(body)))).rejects.toThrow('too large')
  expect(cancel).toHaveBeenCalledOnce()
})
it('does not send an already cancelled subscription', async () => {
  const controller = new AbortController()
  controller.abort()
  const fetchImpl = vi.fn()
  await expect(collect(fetchImpl, controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
  expect(fetchImpl).not.toHaveBeenCalled()
})

const device: DetectedDeviceOut = {
  transport: 'usb_serial',
  device_ref: 'usb_serial:AB12',
  identity: null,
  level: 'board',
  board: 'Dev board',
  board_class: 'mcu',
  mcu_known: true,
  confidence: 0.8,
  evidence: [],
  ambiguous: false,
  last_seen_path: null
}
const frame = (projectId: string, devices: unknown): string =>
  `event: hardware.devices_changed\ndata: ${JSON.stringify({ type: 'hardware.devices_changed', project_id: projectId, devices, at: 1 })}\n\n`

it('yields typed device frames for this project and drops malformed or foreign ones', async () => {
  const fetchImpl = vi.fn().mockResolvedValue(
    response([
      frame('foreign', [device]),
      frame('p1', { not: 'an array' }),
      frame('p1', [{ ...device, level: undefined }]),
      frame(
        'p1',
        Array.from({ length: 65 }, () => device)
      ),
      frame('p1', [device])
    ])
  )
  expect(await collect(fetchImpl)).toEqual([
    { type: 'hardware.devices_changed', devices: [device] }
  ])
})

it.each([
  ['non-array', { devices: [] }],
  ['too many', Array.from({ length: 65 }, () => device)],
  ['missing level', [{ ...device, level: undefined }]],
  ['bad level', [{ ...device, level: 'guess' }]],
  ['non-boolean ambiguous', [{ ...device, ambiguous: 'no' }]],
  ['missing evidence', [{ ...device, evidence: undefined }]],
  ['non-string board', [{ ...device, board: 7 }]],
  ['non-number confidence', [{ ...device, confidence: '0.8' }]],
  ['non-object item', ['x']],
  ['null', null]
])('toDetectedDevices rejects %s without throwing', (_, value) => {
  expect(toDetectedDevices(value)).toBeNull()
})

it('toDetectedDevices accepts an empty list and a 64-item well-formed list', () => {
  expect(toDetectedDevices([])).toEqual([])
  expect(toDetectedDevices(Array.from({ length: 64 }, () => device))).toHaveLength(64)
})

async function collectFor(frames: string[]): Promise<ProjectEvent[]> {
  const events: ProjectEvent[] = []
  for await (const event of streamProjectEvents({
    projectId: PROJECT_ID,
    baseUrl: 'https://api.test',
    getToken: () => 't',
    fetchImpl: vi.fn().mockResolvedValue(response(frames))
  }))
    events.push(event)
  return events
}

it('types a non-2xx as LiveStreamHttpError', async () => {
  await expect(
    collect(vi.fn().mockResolvedValue(new Response(null, { status: 401 })))
  ).rejects.toBeInstanceOf(LiveStreamHttpError)
})

it('decodes every contract frame type for the subscribed project', async () => {
  const events = await collectFor([
    sse('ready', projectReady),
    sse('graph.changed', graphChanged),
    sse('layout.changed', layoutChanged),
    sse('sources.changed', sourcesChanged),
    sse('project.updated', projectUpdated),
    sse('job.updated', jobUpdated),
    sse('access.revoked', projectAccessRevoked)
  ])
  expect(events).toEqual([
    'ready',
    'graph.changed',
    { type: 'layout.changed', version: 7 },
    { type: 'sources.changed' },
    { type: 'project.updated' },
    { type: 'job.updated', jobId: jobUpdated.job_id, status: 'succeeded' },
    { type: 'access.revoked' }
  ])
})

// SOLUSDEV-320: finding frames carry the finding id and its status; a bad status is dropped.
const findingRaised = {
  type: 'finding.raised',
  project_id: PROJECT_ID,
  finding_id: '66666666-6666-4666-8666-666666666666',
  status: 'open',
  at: '2026-09-30T12:00:00+00:00'
}
it('decodes finding.raised|updated|resolved for the subscribed project only', async () => {
  const events = await collectFor([
    sse('finding.raised', findingRaised),
    sse('finding.updated', { ...findingRaised, type: 'finding.updated', status: 'acknowledged' }),
    sse('finding.resolved', { ...findingRaised, type: 'finding.resolved', status: 'resolved' }),
    sse('finding.raised', { ...findingRaised, project_id: 'other' }),
    sse('finding.raised', { ...findingRaised, status: 'exploded' })
  ])
  expect(events).toEqual([
    { type: 'finding.raised', findingId: findingRaised.finding_id, status: 'open' },
    { type: 'finding.updated', findingId: findingRaised.finding_id, status: 'acknowledged' },
    { type: 'finding.resolved', findingId: findingRaised.finding_id, status: 'resolved' }
  ])
})

it('accepts access.revoked scoped to a team (project_id null) on a project stream', async () => {
  const revoked = { ...projectAccessRevoked, project_id: null, team_id: 'team-1' }
  expect(await collectFor([sse('access.revoked', revoked)])).toEqual([{ type: 'access.revoked' }])
})

it.each([
  ['foreign project', 'layout.changed', { ...layoutChanged, project_id: 'other' }],
  ['negative version', 'layout.changed', { ...layoutChanged, version: -1 }],
  ['fractional version', 'layout.changed', { ...layoutChanged, version: 1.5 }],
  ['string version', 'layout.changed', { ...layoutChanged, version: '7' }],
  ['extra field', 'sources.changed', { ...sourcesChanged, name: 'leak' }],
  ['missing field', 'sources.changed', { type: 'sources.changed', project_id: PROJECT_ID }],
  ['non-string source id', 'sources.changed', { ...sourcesChanged, source_id: 4 }],
  ['non-string team id', 'project.updated', { ...projectUpdated, team_id: null }],
  ['unknown job status', 'job.updated', { ...jobUpdated, status: 'exploded' }],
  ['non-string job id', 'job.updated', { ...jobUpdated, job_id: 1 }],
  ['foreign revoke', 'access.revoked', { ...projectAccessRevoked, project_id: 'other' }],
  [
    'unscoped revoke',
    'access.revoked',
    { ...projectAccessRevoked, user_id: null, team_id: null, project_id: null }
  ],
  ['account frame on project stream', 'team.updated', teamUpdated],
  ['type/event-name mismatch', 'layout.changed', { ...sourcesChanged }]
])('drops %s without throwing', async (_name, event, data) => {
  expect(await collectFor([sse(event, data), sse('graph.changed', graphChanged)])).toEqual([
    'graph.changed'
  ])
})

// SOLUSDEV-319: the shared bench view hint carries only the new version.
const benchViewChanged = {
  type: 'bench.view_changed',
  project_id: PROJECT_ID,
  version: 4,
  at: '2026-10-31T21:04:11Z'
}
it('decodes bench.view_changed into a version hint', async () => {
  expect(await collectFor([sse('bench.view_changed', benchViewChanged)])).toEqual([
    { type: 'bench.view_changed', version: 4 }
  ])
})
it.each([
  ['foreign project', { ...benchViewChanged, project_id: 'other' }],
  ['negative version', { ...benchViewChanged, version: -1 }],
  ['extra field', { ...benchViewChanged, view: { display: [] } }]
])('drops a bench.view_changed with %s', async (_name, data) => {
  expect(
    await collectFor([sse('bench.view_changed', data), sse('graph.changed', graphChanged)])
  ).toEqual(['graph.changed'])
})
