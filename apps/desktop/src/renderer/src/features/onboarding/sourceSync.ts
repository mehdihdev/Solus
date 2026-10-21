// Shared sync-polling helpers for real connect flows (GitHub, committed-export
// EDA). Extracted from githubConnect.ts (SOLUSDEV-100) so every connector polls
// and reports sync failures the same way. Transport is injected — no React.
import type { Sync, SyncJob } from '../../lib/api/resources'

export interface SyncPollApi {
  getSyncs: (projectId: string, sourceId: string) => Promise<Sync[]>
}

export const POLL_INTERVAL_MS = 1000
export const POLL_MAX_TRIES = 30

export const defaultSleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms))

/** The latest sync is the most relevant; backend returns history ordered. */
export function latestSync(syncs: Sync[]): Sync | undefined {
  return syncs[0]
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

/** The accepted job is authoritative; history can precede its Sync record. */
export interface SyncJobApi {
  getJob: (jobId: string) => Promise<SyncJob>
}

/** Said when a connect hands a still-running sync to the source row. */
export const STILL_INDEXING_RESULT = 'Connected — still indexing in the background'

/** A job that has stopped: succeeded, failed or cancelled. */
export function isSettledJob(job: SyncJob): boolean {
  return job.status === 'succeeded' || job.status === 'failed' || job.status === 'cancelled'
}

/** Why a polled job did not succeed; null when it succeeded or is still running. */
export function jobFailure(job: SyncJob | undefined): string | null {
  if (!job) return 'Sync timed out.'
  if (job.status !== 'failed' && job.status !== 'cancelled') return null
  return job.error?.message ?? (job.status === 'cancelled' ? 'Sync cancelled.' : 'Sync failed.')
}

/**
 * Poll the accepted job until it settles or the budget runs out. Out of tries,
 * the job comes back as last seen (still queued or running): a long sync is not
 * a failed one, and the caller hands it to the source row.
 */
export async function pollAcceptedSync(
  api: SyncJobApi,
  projectId: string,
  jobId: string,
  sleep: (ms: number) => Promise<void> = defaultSleep
): Promise<SyncJob | undefined> {
  let last: SyncJob | undefined
  for (let attempt = 0; attempt < POLL_MAX_TRIES; attempt += 1) {
    const job = await api.getJob(jobId)
    if (job.id !== jobId || job.project_id !== projectId) {
      throw new Error('The import job does not match this project and request.')
    }
    if (isSettledJob(job)) return job
    last = job
    await sleep(POLL_INTERVAL_MS)
  }
  return last
}

/** Prefer the current source count; history is only an optional fallback. */
export async function indexedSyncDetail(
  api: SyncPollApi,
  projectId: string,
  sourceId: string,
  entityCount: number | undefined
): Promise<string> {
  if (entityCount !== undefined) return `${entityCount} entities indexed`
  const sync = latestSync(await api.getSyncs(projectId, sourceId))
  return sync?.status === 'succeeded'
    ? `${sync.entities_created} entities indexed`
    : 'sync completed'
}
