import type { ApiClient } from '../../lib/api/client'
import {
  addSourceDocument,
  createSource,
  triggerSync,
  getJob,
  type Connection,
  type SelectableItem,
  type Source,
  type Entity
} from '../../lib/api/resources'

export interface ServiceSelection {
  source: Source
  jobId: string | null
}
export interface AttachOptions {
  projectId: string
  connection: Connection
  item: SelectableItem
  sources: Source[]
  client: ApiClient
  assertCurrent: () => void
}
export function supportsWorkspaceService(provider: string): boolean {
  return ['onshape', 'github', 'gitlab'].includes(provider)
}
function accountSources({ projectId, connection, sources }: AttachOptions): Source[] {
  return sources.filter(
    (source) =>
      source.project_id === projectId &&
      source.connection_id === connection.id &&
      source.type === connection.provider
  )
}

/** Reuse I1 binding/selection. Reselecting cached project membership never posts a sync. */
export async function attachServiceDocument(options: AttachOptions): Promise<ServiceSelection> {
  options.assertCurrent()
  if (options.connection.status !== 'connected')
    throw new Error('Reconnect this account in Home first.')
  if (!supportsWorkspaceService(options.connection.provider))
    throw new Error('Open this integration in Sources.')
  return options.connection.provider === 'onshape'
    ? attachOnshape(options)
    : attachRepository(options)
}
async function attachOnshape(options: AttachOptions): Promise<ServiceSelection> {
  const { projectId, connection, item, client, assertCurrent } = options
  let source = accountSources(options)[0]
  if (source && Array.isArray(source.config.documents) && source.config.documents.includes(item.id))
    return { source, jobId: null }
  source ??= await createSource(
    projectId,
    {
      type: 'onshape',
      name: `Onshape · ${connection.account_login ?? 'account'}`,
      connection_id: connection.id
    },
    client
  )
  assertCurrent()
  const accepted = await addSourceDocument(projectId, source.id, item.id, client)
  assertCurrent()
  return { source: accepted.source, jobId: accepted.job_id }
}
async function attachRepository(options: AttachOptions): Promise<ServiceSelection> {
  const { projectId, connection, item, client, assertCurrent } = options
  const repo = item.config?.repo
  const branch = item.config?.branch
  if (typeof repo !== 'string' || !repo || typeof branch !== 'string' || !branch)
    throw new Error('This repository listing has no branch. Refresh this account’s documents.')
  const existing = accountSources(options).find(
    (source) => source.config.repo === repo && source.config.branch === branch
  )
  if (existing) return { source: existing, jobId: null }
  const source = await createSource(
    projectId,
    {
      type: connection.provider,
      name: item.name,
      connection_id: connection.id,
      config: { repo, branch }
    },
    client
  )
  assertCurrent()
  // Another session may have attached it after our project snapshot was read.
  if (source.last_synced_at || source.status === 'syncing') return { source, jobId: null }
  const accepted = await triggerSync(projectId, source.id, client)
  assertCurrent()
  return { source, jobId: accepted.job_id }
}

interface JobOptions {
  projectId: string
  jobId: string
  client: ApiClient
  assertCurrent: () => void
  sleep?: (ms: number) => Promise<void>
}
export async function waitForServiceJob({
  projectId,
  jobId,
  client,
  assertCurrent,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
}: JobOptions): Promise<void> {
  for (let attempt = 0; attempt < 180; attempt += 1) {
    assertCurrent()
    const job = await getJob(jobId, client)
    assertCurrent()
    if (job.project_id !== projectId) throw new Error('The import job belongs to another project.')
    if (job.status === 'succeeded') return
    if (job.status === 'failed' || job.status === 'cancelled')
      throw new Error(
        job.error?.message ?? 'The document import did not finish. Check Sources for details.'
      )
    await sleep(2000)
  }
  throw new Error(
    'The import is still running. Check Sources for progress; it has not been restarted.'
  )
}

export function serviceRoot(
  entities: readonly Entity[],
  sourceId: string,
  documentId: string
): Entity | undefined {
  return entities.find(
    (entity) =>
      entity.source_id === sourceId &&
      (entity.type === 'code_repo' ||
        (entity.type === 'cad_document' && entity.properties?.document_id === documentId))
  )
}
