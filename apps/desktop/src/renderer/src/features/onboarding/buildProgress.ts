// Real build progress for the onboarding Build step (SOLUSDEV-152
// de-simulation): reads the project's actual sources, polls any in-flight sync
// to a terminal state (reusing the SOLUSDEV-100 sourceSync helpers), and reads
// the real entity count from the graph. Transport is injected — no React.
import type { Source, Sync } from '../../lib/api/resources'
import type { BuildLine } from './onboardingStore'
import { latestSync, pollSync, syncErrorMessage, type SyncPollApi } from './sourceSync'

/** The slice of the typed API surface this progress reader depends on. */
export interface BuildProgressApi extends SyncPollApi {
  listSources: (projectId: string) => Promise<Source[]>
  listEntities: (projectId: string) => Promise<{ id: string }[]>
}

export interface BuildProgressDeps {
  api: BuildProgressApi
  /** Push each new snapshot of the real per-source lines to the UI. */
  onLines: (lines: readonly BuildLine[]) => void
  /** Optional sleep override so tests don't actually wait between poll ticks. */
  sleep?: (ms: number) => Promise<void>
}

export interface BuildProgressResult {
  lines: readonly BuildLine[]
  /** Real entity count from the graph; undefined when it could not be read. */
  entityCount?: number
  /** Set when the sources themselves could not be listed. */
  error?: string
}

/**
 * Read the project's real sync state: one line per source, polled to terminal
 * where a sync is in flight. Never throws — an unreadable project resolves to
 * an empty result with `error` so onboarding is never blocked.
 */
export async function runBuildProgress(
  deps: BuildProgressDeps,
  projectId: string
): Promise<BuildProgressResult> {
  let sources: Source[]
  try {
    sources = await deps.api.listSources(projectId)
  } catch (error) {
    return { lines: [], error: messageFrom(error, 'Sources unavailable.') }
  }

  let lines: readonly BuildLine[] = sources.map((source) => ({
    name: source.name,
    detail: 'Checking sync…',
    state: 'pending' as const
  }))
  deps.onLines(lines)
  if (sources.length === 0) return { lines }

  const resolveLine = (index: number, resolved: Pick<BuildLine, 'detail' | 'state'>): void => {
    lines = lines.map((line, i) => (i === index ? { ...line, ...resolved } : line))
    deps.onLines(lines)
  }
  await Promise.all(
    sources.map(async (source, index) => {
      resolveLine(index, await resolveSourceSync(deps, projectId, source))
    })
  )

  const entityCount = await countEntities(deps.api, projectId)
  return entityCount === undefined ? { lines } : { lines, entityCount }
}

/** One source's honest sync outcome: real counts, real errors, or idle. */
async function resolveSourceSync(
  deps: BuildProgressDeps,
  projectId: string,
  source: Source
): Promise<Pick<BuildLine, 'detail' | 'state'>> {
  try {
    const syncs = await deps.api.getSyncs(projectId, source.id)
    let sync = latestSync(syncs)
    if (!sync) return { detail: 'No sync recorded yet', state: 'idle' }
    if (sync.status === 'queued' || sync.status === 'running') {
      sync = await pollSync(deps.api, projectId, source.id, deps.sleep)
      if (!sync) return { detail: 'Sync still running — see Sources later', state: 'idle' }
    }
    if (sync.status === 'failed') return { detail: syncErrorMessage(sync), state: 'failed' }
    return { detail: describeSucceeded(sync), state: 'ok' }
  } catch (error) {
    return { detail: messageFrom(error, 'Sync status unavailable.'), state: 'failed' }
  }
}

function describeSucceeded(sync: Sync): string {
  return `${sync.entities_created} entities · ${sync.relations_created} relations`
}

async function countEntities(
  api: BuildProgressApi,
  projectId: string
): Promise<number | undefined> {
  try {
    const entities = await api.listEntities(projectId)
    return entities.length
  } catch {
    return undefined
  }
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}
