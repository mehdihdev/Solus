// SOLUSDEV-235 / EXT-12 — the typed client for docs/api/extensions.md. Every
// wrapper is asserted against the route plan's exact method, path, body and
// headers with a fake ApiClient / fake fetch; no network.
import { describe, it, expect, vi } from 'vitest'
import type { ApiClient } from './client'
import { ApiError } from './envelope.types'
import {
  deleteExtensionStorage,
  deleteTeamExtensionPolicy,
  extensionAssetUrl,
  extensionBundleUrl,
  fetchExtensionBundle,
  getExtension,
  getExtensionReview,
  getExtensionStorage,
  getWidgetLayout,
  installExtension,
  listExtensionVersions,
  listExtensions,
  listProjectExtensions,
  listTeamExtensionPolicies,
  patchExtensionInstall,
  publishExtension,
  putExtensionStorage,
  putTeamExtensionPolicy,
  putWidgetLayout,
  setExtensionVerified,
  uninstallProjectExtension,
  unpublishExtensionVersion,
  withExtensionAttribution
} from './resources.extensions'

interface Call {
  path: string
  options?: { method?: string; body?: unknown }
}

function stubClient(result: unknown = {}): { client: ApiClient; calls: Call[] } {
  const calls: Call[] = []
  const client: ApiClient = {
    request: vi.fn(async (path: string, options?: Call['options']) => {
      calls.push({ path, options })
      return result as never
    }),
    requestPage: vi.fn(async (path: string, options?: Call['options']) => {
      calls.push({ path, options })
      return { data: result, meta: { has_next: false, next_cursor: null } } as never
    })
  }
  return { client, calls }
}

function fakeFetch(
  status: number,
  body: BodyInit | null,
  headers: Record<string, string> = {}
): { fetchImpl: typeof fetch; calls: { url: string; init: RequestInit }[] } {
  const calls: { url: string; init: RequestInit }[] = []
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init: init ?? {} })
    return new Response(body, { status, headers })
  }) as unknown as typeof fetch
  return { fetchImpl, calls }
}

const transport = (fetchImpl: typeof fetch): Parameters<typeof fetchExtensionBundle>[2] => ({
  baseUrl: 'https://api.test/api/v1',
  getToken: () => 'tok-secret',
  fetchImpl
})

describe('catalog (§4)', () => {
  it('listExtensions GETs /extensions with q, cursor and limit', async () => {
    const { client, calls } = stubClient([])
    const page = await listExtensions({ q: 'bom', cursor: 'c1', limit: 10 }, client)
    expect(calls[0].path).toBe('/extensions?q=bom&cursor=c1&limit=10')
    expect(page.meta.has_next).toBe(false)
  })

  it('listExtensions omits empty query params', async () => {
    const { client, calls } = stubClient([])
    await listExtensions({}, client)
    expect(calls[0].path).toBe('/extensions')
  })

  it('getExtension GETs the slug detail, URL-encoded', async () => {
    const { client, calls } = stubClient({ slug: 'bom' })
    await getExtension('bom', client)
    expect(calls[0].path).toBe('/extensions/bom')
  })

  it('listExtensionVersions pages /extensions/{slug}/versions', async () => {
    const { client, calls } = stubClient([])
    await listExtensionVersions('bom', 'abc', client)
    expect(calls[0].path).toBe('/extensions/bom/versions?cursor=abc')
  })

  it('extensionBundleUrl / extensionAssetUrl are the relative API routes', () => {
    expect(extensionBundleUrl('bom', '1.2.0')).toBe('/extensions/bom/versions/1.2.0/bundle')
    expect(extensionAssetUrl('bom', '1.2.0', 'shots/table.png')).toBe(
      '/extensions/bom/versions/1.2.0/assets/shots/table.png'
    )
  })

  it('fetchExtensionBundle returns the bytes and the X-Solus-Content-Hash header', async () => {
    const bytes = new Uint8Array([80, 75, 3, 4])
    const { fetchImpl, calls } = fakeFetch(200, bytes, {
      'Content-Type': 'application/zip',
      'X-Solus-Content-Hash': 'abc123'
    })
    const result = await fetchExtensionBundle('bom', '1.2.0', transport(fetchImpl))
    expect(calls[0].url).toBe('https://api.test/api/v1/extensions/bom/versions/1.2.0/bundle')
    expect((calls[0].init.headers as Record<string, string>).Authorization).toBe(
      'Bearer tok-secret'
    )
    expect(result.contentHash).toBe('abc123')
    expect(new Uint8Array(result.bytes)).toEqual(bytes)
  })

  it('fetchExtensionBundle throws the envelope error on a non-2xx', async () => {
    const { fetchImpl } = fakeFetch(
      404,
      JSON.stringify({ error: { code: 'not_found', message: 'no' } })
    )
    await expect(fetchExtensionBundle('bom', '9.9.9', transport(fetchImpl))).rejects.toMatchObject({
      status: 404,
      code: 'not_found'
    })
  })

  it('fetchExtensionBundle refuses a response without a content hash', async () => {
    const { fetchImpl } = fakeFetch(200, new Uint8Array([1]))
    await expect(fetchExtensionBundle('bom', '1.2.0', transport(fetchImpl))).rejects.toBeInstanceOf(
      ApiError
    )
  })
})

describe('publishing (§5)', () => {
  it('publishExtension POSTs multipart with the Idempotency-Key header', async () => {
    const { fetchImpl, calls } = fakeFetch(
      202,
      JSON.stringify({ data: { job_id: 'j1', status: 'queued', version: { slug: 'bom' } } })
    )
    const bundle = new Blob([new Uint8Array([80, 75])], { type: 'application/zip' })
    const accepted = await publishExtension(bundle, 'idem-1', transport(fetchImpl))
    expect(calls[0].url).toBe('https://api.test/api/v1/extensions/publish')
    expect(calls[0].init.method).toBe('POST')
    const headers = calls[0].init.headers as Record<string, string>
    expect(headers['Idempotency-Key']).toBe('idem-1')
    expect(headers.Authorization).toBe('Bearer tok-secret')
    expect(headers['Content-Type']).toBeUndefined()
    const form = calls[0].init.body as FormData
    expect(form.get('bundle')).toBeInstanceOf(Blob)
    expect(accepted.job_id).toBe('j1')
  })

  it('getExtensionReview / unpublishExtensionVersion / setExtensionVerified', async () => {
    const { client, calls } = stubClient({})
    await getExtensionReview('bom', '1.3.0', client)
    await unpublishExtensionVersion('bom', '1.3.0', client)
    await setExtensionVerified('bom', true, client)
    expect(calls[0].path).toBe('/extensions/bom/versions/1.3.0/review')
    expect(calls[1]).toMatchObject({
      path: '/extensions/bom/versions/1.3.0',
      options: { method: 'DELETE' }
    })
    expect(calls[2]).toMatchObject({
      path: '/extensions/bom',
      options: { method: 'PATCH', body: { verified: true } }
    })
  })
})

describe('project installs (§6)', () => {
  it('listProjectExtensions pages /projects/{id}/extensions', async () => {
    const { client, calls } = stubClient([])
    await listProjectExtensions('p1', undefined, client)
    expect(calls[0].path).toBe('/projects/p1/extensions')
  })

  it('installExtension PUTs version + grants', async () => {
    const { client, calls } = stubClient({})
    await installExtension(
      'p1',
      'bom',
      { version: '1.2.0', grants: { scopes: ['graph.read'], network: [] } },
      client
    )
    expect(calls[0]).toMatchObject({
      path: '/projects/p1/extensions/bom',
      options: {
        method: 'PUT',
        body: { version: '1.2.0', grants: { scopes: ['graph.read'], network: [] } }
      }
    })
  })

  it('installExtension omits version when not pinned (server picks latest approved)', async () => {
    const { client, calls } = stubClient({})
    await installExtension('p1', 'bom', { grants: { scopes: [], network: [] } }, client)
    expect(calls[0].options?.body).toEqual({ grants: { scopes: [], network: [] } })
  })

  it('patchExtensionInstall PATCHes enabled / settings', async () => {
    const { client, calls } = stubClient({})
    await patchExtensionInstall('p1', 'bom', { enabled: false }, client)
    expect(calls[0]).toMatchObject({
      path: '/projects/p1/extensions/bom',
      options: { method: 'PATCH', body: { enabled: false } }
    })
  })

  it('uninstallProjectExtension DELETEs the install', async () => {
    const { client, calls } = stubClient(undefined)
    await uninstallProjectExtension('p1', 'bom', client)
    expect(calls[0]).toMatchObject({
      path: '/projects/p1/extensions/bom',
      options: { method: 'DELETE' }
    })
  })
})

describe('storage (§7)', () => {
  it('get / put / delete address /storage/{key} with the raw JSON value as the body', async () => {
    const { client, calls } = stubClient({ key: 'cache', value: 'x' })
    await getExtensionStorage('p1', 'bom', 'cache', client)
    await putExtensionStorage('p1', 'bom', 'cache', 'hello', client)
    await deleteExtensionStorage('p1', 'bom', 'cache', client)
    expect(calls[0].path).toBe('/projects/p1/extensions/bom/storage/cache')
    expect(calls[1]).toMatchObject({
      path: '/projects/p1/extensions/bom/storage/cache',
      options: { method: 'PUT', body: 'hello' }
    })
    expect(calls[2].options?.method).toBe('DELETE')
  })
})

describe('widget layout (§8)', () => {
  it('GET and PUT /projects/{id}/widget-layout', async () => {
    const { client, calls } = stubClient({ project_id: 'p1', layout: [], updated_at: null })
    await getWidgetLayout('p1', client)
    await putWidgetLayout('p1', [{ ref: 'ext:bom', size: 'wide' }], client)
    expect(calls[0].path).toBe('/projects/p1/widget-layout')
    expect(calls[1]).toMatchObject({
      path: '/projects/p1/widget-layout',
      options: { method: 'PUT', body: { layout: [{ ref: 'ext:bom', size: 'wide' }] } }
    })
  })
})

describe('team policy (§10)', () => {
  it('list / put / delete under /teams/{id}/extensions/policies', async () => {
    const { client, calls } = stubClient([])
    await listTeamExtensionPolicies('t1', undefined, client)
    await putTeamExtensionPolicy('t1', 'bom', { blocked: true }, client)
    await deleteTeamExtensionPolicy('t1', 'bom', client)
    expect(calls[0].path).toBe('/teams/t1/extensions/policies')
    expect(calls[1]).toMatchObject({
      path: '/teams/t1/extensions/policies/bom',
      options: { method: 'PUT', body: { blocked: true } }
    })
    expect(calls[2]).toMatchObject({
      path: '/teams/t1/extensions/policies/bom',
      options: { method: 'DELETE' }
    })
  })
})

describe('attribution (§9)', () => {
  it('withExtensionAttribution returns the X-Solus-Extension header (+ version when given)', () => {
    expect(withExtensionAttribution('bom')).toEqual({ 'X-Solus-Extension': 'bom' })
    expect(withExtensionAttribution('bom', '1.2.0')).toEqual({
      'X-Solus-Extension': 'bom',
      'X-Solus-Extension-Version': '1.2.0'
    })
  })
})

describe('path hygiene', () => {
  it('URL-encodes every path segment so a hostile slug cannot re-route the request', async () => {
    const { client, calls } = stubClient({})
    await getExtensionStorage('p1', 'bom', 'a/b?c', client)
    await getExtension('../teams', client)
    expect(calls[0].path).toBe('/projects/p1/extensions/bom/storage/a%2Fb%3Fc')
    expect(calls[1].path).toBe('/extensions/..%2Fteams')
  })
})
