// Tests for the shared sync-polling helpers (SOLUSDEV-100). The poll loop is
// also exercised end-to-end by githubConnect.test.ts / edaConnect.test.ts; here
// we pin the pure pieces, especially the SyncError-object message handling.
import { describe, it, expect, vi } from 'vitest'
import type { Sync } from '../../lib/api/resources'
import { latestSync, pollSync, syncErrorMessage } from './sourceSync'

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
  it('returns the last sync in history', () => {
    const older = sync({ id: 'a' })
    const newer = sync({ id: 'b' })
    expect(latestSync([older, newer])?.id).toBe('b')
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
