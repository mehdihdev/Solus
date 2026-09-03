// SOLUSDEV-235 — test fixtures shaped like the Store API rows
// (docs/api/extensions.md §4.1, §4.2, §6.1) and the manifest contract. Test
// data only; never imported by production code.
import type { ExtensionManifest } from '@solus/shared-types'
import type {
  ExtensionCatalogItemApi,
  ExtensionDetailApi,
  ExtensionInstallApi
} from '../../../lib/api/resources.extensions'
import { buildView, catalogSummaryOf, installStateOf, NOT_INSTALLED } from '../extensionLogic'
import type { ExtensionView } from '../extension.types'

export function manifest(over: Partial<ExtensionManifest> = {}): ExtensionManifest {
  return {
    schema_version: 1,
    extension: {
      id: 'bom',
      name: 'BOM',
      version: '1.2.0',
      publisher: 'Solus',
      summary: 'Bill of materials from your EDA project.',
      requires: [['eda']]
    },
    views: {
      widget: { entry: 'widget.html', preferred: 'wide' },
      page: { entry: 'page.html', icon: 'icon.svg', label: 'BOM' }
    },
    permissions: {
      scopes: ['graph.read', 'sources.read'],
      network: ['https://api.octopart.com']
    },
    settings: {
      fields: [
        {
          key: 'refresh',
          type: 'select',
          label: 'Run frequency',
          options: ['every_sync', 'hourly', 'daily', 'manual'],
          default: 'every_sync'
        },
        { key: 'include_dnp', type: 'boolean', label: 'Include DNP parts', default: false },
        { key: 'max_rows', type: 'number', label: 'Max rows', default: 200, min: 10, max: 1000 },
        { key: 'currency', type: 'string', label: 'Currency', default: 'USD' }
      ]
    },
    store: {
      overview: 'OVERVIEW.md',
      privacy_policy: 'PRIVACY.md',
      links: {
        documentation: 'https://docs.solusforge.com/extensions/bom',
        issues: 'https://gitlab.com/solusforge/solus/-/issues'
      },
      screenshots: [],
      sections: []
    },
    ...over
  }
}

export function catalogItem(over: Partial<ExtensionCatalogItemApi> = {}): ExtensionCatalogItemApi {
  return {
    slug: 'bom',
    name: 'BOM',
    summary: 'Bill of materials from your EDA project.',
    publisher: { display_name: 'Solus' },
    verified: true,
    install_count: 412,
    latest_version: { version: '1.2.0', published_at: '2026-09-01T09:12:03.000Z' },
    requires: [['eda']],
    views: ['widget', 'page'],
    updated_at: '2026-09-01T09:12:03.000Z',
    ...over
  }
}

export function detail(over: Partial<ExtensionDetailApi> = {}): ExtensionDetailApi {
  const m = over.manifest ?? manifest()
  return {
    slug: m.extension.id,
    name: m.extension.name,
    summary: m.extension.summary,
    publisher: { display_name: m.extension.publisher },
    verified: true,
    install_count: 412,
    version: {
      version: m.extension.version,
      published_at: '2026-09-01T09:12:03.000Z',
      content_hash: 'a'.repeat(64),
      bundle_size_bytes: 1834112,
      bundle_url: `/api/v1/extensions/${m.extension.id}/versions/${m.extension.version}/bundle`
    },
    manifest: m,
    assets: {
      overview: `/api/v1/extensions/${m.extension.id}/versions/${m.extension.version}/assets/OVERVIEW.md`,
      privacy_policy: `/api/v1/extensions/${m.extension.id}/versions/${m.extension.version}/assets/PRIVACY.md`,
      icon: null,
      screenshots: [],
      sections: []
    },
    created_at: '2026-08-20T14:02:11.000Z',
    updated_at: '2026-09-01T09:12:03.000Z',
    ...over
  }
}

export function installRow(over: Partial<ExtensionInstallApi> = {}): ExtensionInstallApi {
  const m = over.version?.manifest ?? manifest()
  return {
    extension: {
      slug: m.extension.id,
      name: m.extension.name,
      verified: true,
      publisher: { display_name: m.extension.publisher }
    },
    version: {
      version: m.extension.version,
      content_hash: 'a'.repeat(64),
      bundle_size_bytes: 1834112,
      bundle_url: `/api/v1/extensions/${m.extension.id}/versions/${m.extension.version}/bundle`,
      manifest: m
    },
    enabled: true,
    settings: { refresh: 'hourly' },
    granted_scopes: ['graph.read', 'sources.read'],
    granted_network: ['https://api.octopart.com'],
    update_available: null,
    policy: { blocked: false, default_installed: false },
    installed_by: '019ebe5b-7aca-7770-acbb-c1897f15f46e',
    installed_at: '2026-08-28T10:00:00.000Z',
    updated_at: '2026-09-01T12:30:00.000Z',
    ...over
  }
}

/** A view for one extension: installed (from an install row) or not. */
export function viewOf(
  options: {
    manifest?: ExtensionManifest
    install?: Partial<ExtensionInstallApi> | null
    catalog?: Partial<ExtensionCatalogItemApi>
    connected?: string[]
    blocked?: boolean
  } = {}
): ExtensionView {
  const m = options.manifest ?? manifest()
  const item = catalogItem({
    slug: m.extension.id,
    name: m.extension.name,
    summary: m.extension.summary,
    publisher: { display_name: m.extension.publisher },
    latest_version: { version: m.extension.version, published_at: '2026-09-01T09:12:03.000Z' },
    requires: m.extension.requires.map((g) => [...g]),
    views: Object.keys(m.views),
    ...options.catalog
  })
  const row =
    options.install === null || options.install === undefined
      ? null
      : installRow({ ...options.install, version: { ...installRow().version, manifest: m } })
  return buildView({
    catalog: catalogSummaryOf(item),
    manifest: m,
    state: row ? installStateOf(row) : NOT_INSTALLED,
    connected: new Set((options.connected ?? []) as never[]),
    blocked: options.blocked ?? false
  })
}
