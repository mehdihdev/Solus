// SOLUSDEV-319 — typed wrappers for the teleoperation routes (API-implementation §15).
import { describe, it, expect, vi } from 'vitest'
import { getTeleop, previewTeleop, releaseRobot, startTeleop, stopTeleop } from './resources'
import type { ApiClient } from './client'

function stub(): { client: ApiClient; calls: { path: string; options?: unknown }[] } {
  const calls: { path: string; options?: unknown }[] = []
  const client = {
    request: vi.fn(async (path: string, options?: unknown) => {
      calls.push({ path, options })
      return null as never
    }),
    requestPage: vi.fn()
  } as ApiClient
  return { client, calls }
}

describe('teleop api', () => {
  it('previews with both session ids', async () => {
    const { client, calls } = stub()
    await previewTeleop('p1', { leader_session_id: 'a', follower_session_id: 'b' }, client)
    expect(calls[0]).toEqual({
      path: '/projects/p1/bench/teleop/preview',
      options: { method: 'POST', body: { leader_session_id: 'a', follower_session_id: 'b' } }
    })
  })
  it('starts with preview_id and confirm', async () => {
    const { client, calls } = stub()
    await startTeleop('p1', 'prev', client)
    expect(calls[0]).toEqual({
      path: '/projects/p1/bench/teleop',
      options: { method: 'POST', body: { preview_id: 'prev', confirm: true } }
    })
  })
  it('gets and stops teleop', async () => {
    const { client, calls } = stub()
    await getTeleop('p1', client)
    await stopTeleop('p1', client)
    expect(calls[0].path).toBe('/projects/p1/bench/teleop')
    expect(calls[1]).toEqual({
      path: '/projects/p1/bench/teleop/stop',
      options: { method: 'POST' }
    })
  })
  it('releases a robot session with confirm', async () => {
    const { client, calls } = stub()
    await releaseRobot('p1', 's9', client)
    expect(calls[0]).toEqual({
      path: '/projects/p1/bench/sessions/s9/release',
      options: { method: 'POST', body: { confirm: true } }
    })
  })
})
