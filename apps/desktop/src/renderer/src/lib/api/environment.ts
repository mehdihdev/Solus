// Environment divergences client (SOLUSDEV-320). Hand-written to docs/api/solus.md
// §2.1 (`EnvironmentDivergences`), the way `findings.ts` is: the generated schema
// lags the route plan.
import { api, type ApiClient } from './client'

export type DivergenceCause = 'missing' | 'version_drift' | 'platform_build' | 'extra'

export interface DivergenceItem {
  name: string
  expected?: string | null
  actual?: string | null
  detail?: string | null
}

export interface MachineDivergences {
  machine_id: string
  hostname: string
  causes: Array<{ cause: DivergenceCause; items: DivergenceItem[] }>
}

/** Wire shape of `GET /projects/{id}/environment/divergences`. */
export interface EnvironmentDivergencesDoc {
  schema_version: 1
  computed_at: string
  spec_entry_id: string | null
  machines: MachineDivergences[]
}

export function getEnvironmentDivergences(
  projectId: string,
  client: ApiClient = api
): Promise<EnvironmentDivergencesDoc> {
  return client.request<EnvironmentDivergencesDoc>(`/projects/${projectId}/environment/divergences`)
}
