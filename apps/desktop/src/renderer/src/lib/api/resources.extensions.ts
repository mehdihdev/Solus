// SOLUSDEV-235 / EXT-12 — typed wrappers for the Extensions & Store route plan
// (docs/api/extensions.md). Paths and response field names follow that plan
// verbatim; the API's own snake_case is kept (API.md §1.4) and every shape is
// Api-suffixed like resources.ts.
//
// Two routes cannot ride the JSON envelope client: the bundle (zip bytes + an
// `X-Solus-Content-Hash` header the installer must read) and publish
// (multipart). Those use fetch HERE and only here (the solStream.ts idiom),
// through the same base URL and token source as the app client.
import type { ExtensionManifest, PermissionScope, WidgetSlotSize } from '@solus/shared-types'
import {
  api,
  apiBaseUrl,
  apiToken,
  joinUrl,
  unwrapEnvelope,
  type ApiClient,
  type Page,
  type RequestOptions
} from './client'
import { ApiError } from './envelope.types'

// `RequestOptions.method` predates this plan — the extensions surface is the
// first PUT the desktop makes, and client.ts is outside EXT-12's ownership.
// The transport forwards the verb verbatim (`req.method ?? 'GET'`), so the
// cast is type-only; widening the union is a one-line client.ts follow-up
// (flagged in the completion report).
const PUT = 'PUT' as unknown as RequestOptions['method']

function putJson<T>(client: ApiClient, path: string, body: unknown): Promise<T> {
  return client.request<T>(path, { method: PUT, body })
}

/* ---------------- shapes ---------------- */

export interface ExtensionPublisherApi {
  display_name: string
}

export interface ExtensionLatestVersionApi {
  version: string
  published_at: string
}

/** One catalog row (§4.1). */
export interface ExtensionCatalogItemApi {
  slug: string
  name: string
  summary: string
  publisher: ExtensionPublisherApi
  verified: boolean
  install_count: number
  latest_version: ExtensionLatestVersionApi
  requires: string[][]
  views: string[]
  updated_at: string
}

export interface ExtensionVersionDetailApi {
  version: string
  published_at: string
  content_hash: string
  bundle_size_bytes: number
  /** A relative API route (§3) — never a storage locator. */
  bundle_url: string
}

export interface ExtensionAssetSectionApi {
  title: string
  url: string
}

export interface ExtensionAssetsApi {
  overview: string
  privacy_policy: string | null
  icon: string | null
  screenshots: string[]
  sections: ExtensionAssetSectionApi[]
}

/** The detail (§4.2). `version`/`manifest`/`assets` are null only in the
 *  publisher's own unreleased view. */
export interface ExtensionDetailApi {
  slug: string
  name: string
  summary: string
  publisher: ExtensionPublisherApi
  verified: boolean
  install_count: number
  version: ExtensionVersionDetailApi | null
  manifest: ExtensionManifest | null
  assets: ExtensionAssetsApi | null
  created_at: string
  updated_at: string
}

export type ExtensionReviewStatusApi = 'pending' | 'checking' | 'approved' | 'rejected'

/** One version row (§4.3). `review_problems` appears only to the publisher on a rejection. */
export interface ExtensionVersionApi {
  version: string
  review_status: ExtensionReviewStatusApi
  review_problems?: string[]
  published_at: string | null
  content_hash: string
  bundle_size_bytes: number
  created_at: string
}

export interface ExtensionPublishedVersionApi {
  slug: string
  version: string
  review_status: ExtensionReviewStatusApi
  content_hash: string
  bundle_size_bytes: number
  bundle_url: string
  review_url: string
  created_at: string
}

/** The 202 body of a publish (§5.1). */
export interface ExtensionPublishAcceptedApi {
  job_id: string
  status: string
  version: ExtensionPublishedVersionApi
}

export interface ExtensionReviewApi {
  slug: string
  version: string
  review_status: ExtensionReviewStatusApi
  review_problems: string[]
  checked_at: string | null
  published_at: string | null
}

export interface ExtensionGrantsApi {
  scopes: PermissionScope[]
  network: string[]
}

export type ExtensionSettingsValuesApi = Record<string, boolean | number | string>

export interface ExtensionInstallSummaryApi {
  slug: string
  name: string
  verified: boolean
  publisher: ExtensionPublisherApi
}

export interface ExtensionPinnedVersionApi extends ExtensionVersionDetailApi {
  /** The PINNED version's manifest — settings validate against what is installed. */
  manifest: ExtensionManifest
}

export interface ExtensionUpdateAvailableApi {
  version: string
  widens_permissions: boolean
}

export interface ExtensionPolicySummaryApi {
  blocked: boolean
  default_installed: boolean
}

/** One installed extension (§6.1) — the bridge's install+policy snapshot row. */
export interface ExtensionInstallApi {
  extension: ExtensionInstallSummaryApi
  version: ExtensionPinnedVersionApi
  enabled: boolean
  settings: ExtensionSettingsValuesApi
  granted_scopes: PermissionScope[]
  granted_network: string[]
  update_available: ExtensionUpdateAvailableApi | null
  policy: ExtensionPolicySummaryApi
  installed_by: string
  installed_at: string
  updated_at: string
}

export interface ExtensionInstallInput {
  version?: string
  grants: ExtensionGrantsApi
}

export interface ExtensionInstallPatch {
  enabled?: boolean
  settings?: ExtensionSettingsValuesApi
}

/** One `storage.own` value (§7). `value` is opaque JSON. */
export interface ExtensionStorageValueApi {
  key: string
  value: unknown
  size_bytes: number
  updated_at: string
}

export interface WidgetLayoutSlotApi {
  ref: string
  size: WidgetSlotSize
}

export interface WidgetLayoutApi {
  project_id: string
  layout: WidgetLayoutSlotApi[]
  updated_at: string | null
}

export interface TeamExtensionPolicyApi {
  extension: { slug: string; name: string; verified: boolean }
  blocked: boolean
  default_installed: boolean
  default_settings: Record<string, unknown>
  updated_by: string
  updated_at: string
}

export interface TeamExtensionPolicyInput {
  blocked?: boolean
  default_installed?: boolean
  default_settings?: Record<string, unknown>
}

/* ---------------- helpers ---------------- */

const seg = encodeURIComponent

function withQuery(path: string, params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const query = search.toString()
  return query ? `${path}?${query}` : path
}

/** The fetch-based routes' transport. Defaults to the app client's configuration. */
export interface ExtensionRawTransport {
  baseUrl?: string
  getToken?: () => Promise<string | null> | string | null
  fetchImpl?: typeof fetch
}

async function rawSend(
  path: string,
  init: { method: string; headers?: Record<string, string>; body?: BodyInit },
  transport: ExtensionRawTransport
): Promise<Response> {
  const fetchImpl = transport.fetchImpl ?? globalThis.fetch
  const token = await (transport.getToken ?? apiToken)()
  const headers: Record<string, string> = { ...(init.headers ?? {}) }
  if (token) headers.Authorization = `Bearer ${token}`
  return fetchImpl(joinUrl(transport.baseUrl ?? apiBaseUrl, path), {
    method: init.method,
    headers,
    body: init.body
  })
}

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

/* ---------------- §4 catalog ---------------- */

export interface ExtensionListQuery {
  q?: string
  cursor?: string
  limit?: number
}

export function listExtensions(
  query: ExtensionListQuery = {},
  client: ApiClient = api
): Promise<Page<ExtensionCatalogItemApi[]>> {
  const { q, cursor, limit } = query
  return client.requestPage<ExtensionCatalogItemApi[]>(
    withQuery('/extensions', { q, cursor, limit })
  )
}

export function getExtension(slug: string, client: ApiClient = api): Promise<ExtensionDetailApi> {
  return client.request<ExtensionDetailApi>(`/extensions/${seg(slug)}`)
}

export function listExtensionVersions(
  slug: string,
  cursor?: string,
  client: ApiClient = api
): Promise<Page<ExtensionVersionApi[]>> {
  return client.requestPage<ExtensionVersionApi[]>(
    withQuery(`/extensions/${seg(slug)}/versions`, { cursor })
  )
}

export function extensionBundleUrl(slug: string, version: string): string {
  return `/extensions/${seg(slug)}/versions/${seg(version)}/bundle`
}

export function extensionAssetUrl(slug: string, version: string, path: string): string {
  const encodedPath = path.split('/').map(seg).join('/')
  return `/extensions/${seg(slug)}/versions/${seg(version)}/assets/${encodedPath}`
}

export interface ExtensionBundle {
  bytes: ArrayBuffer
  /** `X-Solus-Content-Hash` — sha256 hex of the bytes, verified by main before caching. */
  contentHash: string
}

/** GET the zip (§4.4). The desktop MAIN process is the intended consumer. */
export async function fetchExtensionBundle(
  slug: string,
  version: string,
  transport: ExtensionRawTransport = {}
): Promise<ExtensionBundle> {
  const res = await rawSend(
    extensionBundleUrl(slug, version),
    { method: 'GET', headers: { Accept: 'application/zip' } },
    transport
  )
  if (!res.ok) unwrapEnvelope(res.status, await parseBody(res))
  const contentHash = res.headers.get('X-Solus-Content-Hash')
  if (!contentHash) {
    throw new ApiError(res.status, 'content_hash_missing', 'Bundle response carried no hash')
  }
  return { bytes: await res.arrayBuffer(), contentHash }
}

/* ---------------- §5 publishing ---------------- */

/** POST /extensions/publish (§5.1) — multipart, `Idempotency-Key` required. */
export async function publishExtension(
  bundle: Blob,
  idempotencyKey: string,
  transport: ExtensionRawTransport = {}
): Promise<ExtensionPublishAcceptedApi> {
  const form = new FormData()
  form.append('bundle', bundle, 'bundle.zip')
  // No Content-Type: fetch sets the multipart boundary itself.
  const res = await rawSend(
    '/extensions/publish',
    {
      method: 'POST',
      headers: { Accept: 'application/json', 'Idempotency-Key': idempotencyKey },
      body: form
    },
    transport
  )
  return unwrapEnvelope<ExtensionPublishAcceptedApi>(res.status, await parseBody(res))
}

export function getExtensionReview(
  slug: string,
  version: string,
  client: ApiClient = api
): Promise<ExtensionReviewApi> {
  return client.request<ExtensionReviewApi>(
    `/extensions/${seg(slug)}/versions/${seg(version)}/review`
  )
}

export function unpublishExtensionVersion(
  slug: string,
  version: string,
  client: ApiClient = api
): Promise<void> {
  return client.request<void>(`/extensions/${seg(slug)}/versions/${seg(version)}`, {
    method: 'DELETE'
  })
}

/** Staff-only verified badge (§5.4). */
export function setExtensionVerified(
  slug: string,
  verified: boolean,
  client: ApiClient = api
): Promise<ExtensionDetailApi> {
  return client.request<ExtensionDetailApi>(`/extensions/${seg(slug)}`, {
    method: 'PATCH',
    body: { verified }
  })
}

/* ---------------- §6 project installs ---------------- */

export function listProjectExtensions(
  projectId: string,
  cursor?: string,
  client: ApiClient = api
): Promise<Page<ExtensionInstallApi[]>> {
  return client.requestPage<ExtensionInstallApi[]>(
    withQuery(`/projects/${seg(projectId)}/extensions`, { cursor })
  )
}

export function installExtension(
  projectId: string,
  slug: string,
  input: ExtensionInstallInput,
  client: ApiClient = api
): Promise<ExtensionInstallApi> {
  return putJson<ExtensionInstallApi>(
    client,
    `/projects/${seg(projectId)}/extensions/${seg(slug)}`,
    input
  )
}

export function patchExtensionInstall(
  projectId: string,
  slug: string,
  patch: ExtensionInstallPatch,
  client: ApiClient = api
): Promise<ExtensionInstallApi> {
  return client.request<ExtensionInstallApi>(
    `/projects/${seg(projectId)}/extensions/${seg(slug)}`,
    {
      method: 'PATCH',
      body: patch
    }
  )
}

/** DELETE the install row and this extension's storage (§6.4). */
export function uninstallProjectExtension(
  projectId: string,
  slug: string,
  client: ApiClient = api
): Promise<void> {
  return client.request<void>(`/projects/${seg(projectId)}/extensions/${seg(slug)}`, {
    method: 'DELETE'
  })
}

/* ---------------- §7 storage ---------------- */

function storagePath(projectId: string, slug: string, key: string): string {
  return `/projects/${seg(projectId)}/extensions/${seg(slug)}/storage/${seg(key)}`
}

export function getExtensionStorage(
  projectId: string,
  slug: string,
  key: string,
  client: ApiClient = api
): Promise<ExtensionStorageValueApi> {
  return client.request<ExtensionStorageValueApi>(storagePath(projectId, slug, key))
}

/** PUT one value; the body IS the raw JSON value (§7). */
export function putExtensionStorage(
  projectId: string,
  slug: string,
  key: string,
  value: unknown,
  client: ApiClient = api
): Promise<ExtensionStorageValueApi> {
  return putJson<ExtensionStorageValueApi>(client, storagePath(projectId, slug, key), value)
}

export function deleteExtensionStorage(
  projectId: string,
  slug: string,
  key: string,
  client: ApiClient = api
): Promise<void> {
  return client.request<void>(storagePath(projectId, slug, key), { method: 'DELETE' })
}

/* ---------------- §8 widget layout ---------------- */

export function getWidgetLayout(
  projectId: string,
  client: ApiClient = api
): Promise<WidgetLayoutApi> {
  return client.request<WidgetLayoutApi>(`/projects/${seg(projectId)}/widget-layout`)
}

export function putWidgetLayout(
  projectId: string,
  layout: readonly WidgetLayoutSlotApi[],
  client: ApiClient = api
): Promise<WidgetLayoutApi> {
  return putJson<WidgetLayoutApi>(client, `/projects/${seg(projectId)}/widget-layout`, { layout })
}

/* ---------------- §10 team policy ---------------- */

export function listTeamExtensionPolicies(
  teamId: string,
  cursor?: string,
  client: ApiClient = api
): Promise<Page<TeamExtensionPolicyApi[]>> {
  return client.requestPage<TeamExtensionPolicyApi[]>(
    withQuery(`/teams/${seg(teamId)}/extensions/policies`, { cursor })
  )
}

export function putTeamExtensionPolicy(
  teamId: string,
  slug: string,
  input: TeamExtensionPolicyInput,
  client: ApiClient = api
): Promise<TeamExtensionPolicyApi> {
  return putJson<TeamExtensionPolicyApi>(
    client,
    `/teams/${seg(teamId)}/extensions/policies/${seg(slug)}`,
    input
  )
}

export function deleteTeamExtensionPolicy(
  teamId: string,
  slug: string,
  client: ApiClient = api
): Promise<void> {
  return client.request<void>(`/teams/${seg(teamId)}/extensions/policies/${seg(slug)}`, {
    method: 'DELETE'
  })
}

/* ---------------- §9 attribution ---------------- */

/** Headers the host adds to a SOL turn made on an extension's behalf (§9,
 *  architecture §6.6). Only the desktop host ever sets these; the server
 *  verifies the install and grant regardless. */
export function withExtensionAttribution(
  slug: string,
  version?: string
): Readonly<Record<string, string>> {
  return {
    'X-Solus-Extension': slug,
    ...(version === undefined ? {} : { 'X-Solus-Extension-Version': version })
  }
}
