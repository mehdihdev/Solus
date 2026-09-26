import { api, type ApiClient } from './client'

export async function reconcileWidgetGraph(
  projectId: string,
  signal?: AbortSignal,
  client: ApiClient = api
): Promise<void> {
  await client.request(`/projects/${encodeURIComponent(projectId)}/widgets/graph/reconcile`, {
    method: 'POST',
    signal
  })
}
