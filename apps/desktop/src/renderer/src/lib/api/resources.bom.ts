// SOLUSDEV-246 (STORE ST4) — the BOM widget's typed client
// (docs/api/widget-bundles.md §11). First-party bundle routes live under
// `/projects/{id}/widgets/bom/…` behind the install guard: a 404 means the
// bundle is not installed, disabled or blocked in this project.
import { api, apiBaseUrl, apiToken, joinUrl, type ApiClient } from './client'

export type BomLifecycleState = 'planned' | 'ordered' | 'received' | 'installed' | 'retired'
export type BomRowKind = 'design' | 'raw_material' | 'purchase'
export type BomItemCategory = 'raw_material' | 'purchase'

export interface BomSourceApi {
  entity_id: string
  kind: string
  domain: string
  name: string
}

export interface BomRowApi {
  key: string
  kind: BomRowKind
  name: string
  part_number: string | null
  manufacturer: string | null
  quantity: number
  state: BomLifecycleState
  supplier: string | null
  unit_cost: number | null
  line_cost: number | null
  notes: string | null
  sources: BomSourceApi[]
  item_id: string | null
  canonical_id: string | null
}

export interface BomTotalsApi {
  rows: number
  priced_rows: number
  line_cost_total: number
  cost_target: number | null
  over_target: boolean | null
}

export interface BomConfigApi {
  preferred_suppliers: string[]
  cost_target: number | null
  currency: string
}

export interface BomViewApi {
  slug: string
  rows: BomRowApi[]
  totals: BomTotalsApi
  config: BomConfigApi
  states: BomLifecycleState[]
  truncated: boolean
}

export interface BomItemInput {
  name: string
  category: BomItemCategory
  quantity?: number
  state?: BomLifecycleState
  part_number?: string
  manufacturer?: string
  supplier?: string
  unit_cost?: number
  notes?: string
}

export interface BomRowPatch {
  name?: string
  quantity?: number
  state?: BomLifecycleState
  supplier?: string
  unit_cost?: number
  notes?: string
}

const seg = encodeURIComponent

function base(projectId: string): string {
  return `/projects/${seg(projectId)}/widgets/bom`
}

export function getBomView(projectId: string, client: ApiClient = api): Promise<BomViewApi> {
  return client.request<BomViewApi>(`${base(projectId)}/rows`)
}

export function createBomRow(
  projectId: string,
  input: BomItemInput,
  client: ApiClient = api
): Promise<BomRowApi> {
  return client.request<BomRowApi>(`${base(projectId)}/rows`, { method: 'POST', body: input })
}

export function patchBomRow(
  projectId: string,
  key: string,
  patch: BomRowPatch,
  client: ApiClient = api
): Promise<BomRowApi> {
  return client.request<BomRowApi>(`${base(projectId)}/rows/${seg(key)}`, {
    method: 'PATCH',
    body: patch
  })
}

export function deleteBomRow(
  projectId: string,
  key: string,
  client: ApiClient = api
): Promise<void> {
  return client.request<void>(`${base(projectId)}/rows/${seg(key)}`, { method: 'DELETE' })
}

/** The raw CSV transport (the envelope client only speaks JSON). */
export interface BomCsvTransport {
  baseUrl?: string
  getToken?: () => Promise<string | null> | string | null
  fetchImpl?: typeof fetch
}

/** GET …/export.csv → the CSV text, or throws with the HTTP status. */
export async function fetchBomCsv(
  projectId: string,
  transport: BomCsvTransport = {}
): Promise<string> {
  const fetchImpl = transport.fetchImpl ?? globalThis.fetch
  const token = await (transport.getToken ?? apiToken)()
  const headers: Record<string, string> = { Accept: 'text/csv' }
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetchImpl(
    joinUrl(transport.baseUrl ?? apiBaseUrl, `${base(projectId)}/export.csv`),
    {
      method: 'GET',
      headers
    }
  )
  if (!res.ok) throw new Error(`Export failed with status ${res.status}`)
  return res.text()
}
