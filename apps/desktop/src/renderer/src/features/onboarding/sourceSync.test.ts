// Tests for the shared sync-polling helpers (SOLUSDEV-100). The poll loop is
// also exercised end-to-end by githubConnect.test.ts / edaConnect.test.ts; here
// we pin the pure pieces, especially the SyncError-object message handling.
import { describe, it, expect, vi } from 'vitest'
import type { Sync } from '../../lib/api/resources'
import {
  latestSync,
  pollSync,
  pollAcceptedSync,
  indexedSyncDetail,
  syncErrorMessage
} from './sourceSync'

function sync(overrides: Partial<Sync> = {}): Sync {
  return {
    id: 'sy1',
    status: 'succeeded',
    entities_created: 0,
    relations_created: 0,
    errors: [],
    ...overrides
  }
}

const noSleep = async (): Promise<void> => {}

describe('syncErrorMessage', () => {
  it('uses a plain-string error when present', () => {
    expect(syncErrorMessage(sync({ errors: ['boom'] }))).toBe('boom')
  })

  it('unwraps the backend SyncError object shape', () => {
    expect(syncErrorMessage(sync({ errors: [{ item: 'parse', message: 'bad netlist' }] }))).toBe(
      'bad netlist'
    )
  })

  it('falls back to a generic message when errors are empty or unusable', () => {
    expect(syncErrorMessage(sync())).toBe('Sync failed.')
    expect(syncErrorMessage(sync({ errors: [{ item: 'x' }] }))).toBe('Sync failed.')
  })
})

describe('latestSync / pollSync', () => {
  it('returns the first sync in newest-first history', () => {
    const older = sync({ id: 'a' })
    const newer = sync({ id: 'b' })
    expect(latestSync([newer, older])?.id).toBe('b')
  })

  it('polls until the latest sync is terminal', async () => {
    const getSyncs = vi
      .fn<(projectId: string, sourceId: string) => Promise<Sync[]>>()
      .mockResolvedValueOnce([sync({ status: 'running' })])
      .mockResolvedValueOnce([sync({ status: 'succeeded', entities_created: 3 })])
    const result = await pollSync({ getSyncs }, 'p1', 's1', noSleep)
    expect(result?.entities_created).toBe(3)
    expect(getSyncs).toHaveBeenCalledTimes(2)
  })

  it('returns undefined on timeout', async () => {
    const getSyncs = vi.fn(async () => [sync({ status: 'running' })])
    const result = await pollSync({ getSyncs }, 'p1', 's1', noSleep)
    expect(result).toBeUndefined()
  })
})

describe('accepted sync job', () => {
  it('waits for its accepted job despite an older completed history', async () => {
    const getJob = vi
      .fn()
      .mockResolvedValueOnce({ id: 'j1', project_id: 'p1', status: 'queued', error: null })
      .mockResolvedValueOnce({
        id: 'j1',
        project_id: 'p1',
        status: 'failed',
        error: { message: 'Current quota exhausted' }
      })
    const result = await pollAcceptedSync({ getJob }, 'p1', 'j1', noSleep)
    expect(result?.error?.message).toBe('Current quota exhausted')
    expect(getJob).toHaveBeenCalledTimes(2)
    expect(getJob).toHaveBeenNthCalledWith(2, 'j1')
  })

  it.each([
    { id: 'other', project_id: 'p1' },
    { id: 'j1', project_id: 'foreign' }
  ])('refuses mismatched job identity %o', async (identity) => {
    const getJob = vi.fn(async () => ({ ...identity, status: 'succeeded' as const, error: null }))
    await expect(pollAcceptedSync({ getJob }, 'p1', 'j1', noSleep)).rejects.toThrow(/job/i)
  })

  it('returns cancellation and times out without retrying the sync', async () => {
    const getJob = vi.fn(async () => ({
      id: 'j1',
      project_id: 'p1',
      status: 'cancelled' as const,
      error: null
    }))
    expect((await pollAcceptedSync({ getJob }, 'p1', 'j1', noSleep))?.status).toBe('cancelled')
    const pending = vi.fn(async () => ({
      id: 'j1',
      project_id: 'p1',
      status: 'running' as const,
      error: null
    }))
    // Out of tries on a live job: hand back the job as last seen, so the
    // caller can tell "still running" from a failure.
    expect((await pollAcceptedSync({ getJob: pending }, 'p1', 'j1', noSleep))?.status).toBe(
      'running'
    )
  })
})

describe('indexed sync detail', () => {
  it('uses known source counts, including zero, without another history request', async () => {
    const getSyncs = vi.fn(async () => {
      throw new Error('history unavailable')
    })
    expect(await indexedSyncDetail({ getSyncs }, 'p1', 's1', 0)).toBe('0 entities indexed')
    expect(await indexedSyncDetail({ getSyncs }, 'p1', 's1', 12)).toBe('12 entities indexed')
    expect(getSyncs).not.toHaveBeenCalled()
  })

  it('uses newest successful history only when source count is absent', async () => {
    const getSyncs = vi.fn(async () => [
      sync({ entities_created: 3 }),
      sync({ entities_created: 9 })
    ])
    expect(await indexedSyncDetail({ getSyncs }, 'p1', 's1', undefined)).toBe('3 entities indexed')
    expect(getSyncs).toHaveBeenCalledWith('p1', 's1')
  })

  it('does not claim indexed counts from failed or missing history', async () => {
    const getSyncs = vi
      .fn()
      .mockResolvedValueOnce([sync({ status: 'failed' })])
      .mockResolvedValueOnce([])
    expect(await indexedSyncDetail({ getSyncs }, 'p1', 's1', undefined)).toBe('sync completed')
    expect(await indexedSyncDetail({ getSyncs }, 'p1', 's1', undefined)).toBe('sync completed')
  })
})
