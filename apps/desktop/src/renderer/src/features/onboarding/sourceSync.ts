// Shared sync-polling helpers for real connect flows (GitHub, committed-export
// EDA). Extracted from githubConnect.ts (SOLUSDEV-100) so every connector polls
// and reports sync failures the same way. Transport is injected — no React.
import type { Sync } from '../../lib/api/resources'

export interface SyncPollApi {
  getSyncs: (projectId: string, sourceId: string) => Promise<Sync[]>
}

export const POLL_INTERVAL_MS = 1000
export const POLL_MAX_TRIES = 30

export const defaultSleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms))

/** The latest sync is the most relevant; backend returns history ordered. */
export function latestSync(syncs: Sync[]): Sync | undefined {
  return syncs[syncs.length - 1]
}

/**
 * Poll the source's syncs until the latest reaches a terminal state or we run
 * out of tries. Returns the terminal sync, or undefined on timeout.
 */
export async function pollSync(
  api: SyncPollApi,
  projectId: string,
  sourceId: string,
  sleep: (ms: number) => Promise<void> = defaultSleep
): Promise<Sync | undefined> {
  for (let attempt = 0; attempt < POLL_MAX_TRIES; attempt += 1) {
    const syncs = await api.getSyncs(projectId, sourceId)
    const latest = latestSync(syncs)
    if (latest && (latest.status === 'succeeded' || latest.status === 'failed')) {
      return latest
    }
    await sleep(POLL_INTERVAL_MS)
  }
  return undefined
}

/** First useful message from a failed sync's errors (string or SyncError shape). */
export function syncErrorMessage(sync: Sync): string {
  const first = sync.errors[0]
  if (typeof first === 'string' && first) return first
  if (first && typeof first === 'object' && 'message' in first) {
    const message = (first as { message: unknown }).message
    if (typeof message === 'string' && message) return message
  }
  return 'Sync failed.'
}
