// SOLUSDEV-235 / EXT-13 — test doubles for the frame/page/window surfaces: a
// contract-shaped manifest, a §6.1 install row, and a fake desktop bridge with
// an in-memory index. Every field is overridable so a test states only what
// it is about.
import { vi } from 'vitest'
import type { ExtensionManifest } from '@solus/shared-types'
import type { ExtensionsBridge } from '../../../../lib/desktopBridge'
import type { ExtensionInstallApi } from '../../../../lib/api/resources.extensions'
import type { InstalledBundleDeps } from '../installedBundle'

export function fakeManifest(overrides: Partial<ExtensionManifest> = {}): ExtensionManifest {
  return {
    schema_version: 1,
    graph: { kinds: [] },
    tools: { names: [] },
    extension: {
      id: 'bom',
      name: 'BOM',
      version: '1.2.0',
      publisher: 'Solus',
      summary: 'Bill of materials',
      requires: []
    },
    views: {
      widget: { entry: 'widget.html', preferred: 'standard' },
      page: { entry: 'page.html', icon: 'icon.svg', label: 'BOM' },
      window: { entry: 'window.html', title: 'BOM window', width: 900, height: 600 }
    },
    permissions: { scopes: ['graph.read'], network: [] },
    settings: { fields: [] },
    store: { overview: 'OVERVIEW.md', links: {}, screenshots: [], sections: [] },
    ...overrides
  }
}

export function fakeInstall(overrides: Partial<ExtensionInstallApi> = {}): ExtensionInstallApi {
  return {
    extension: {
      slug: 'bom',
      name: 'BOM',
      verified: true,
      publisher: { display_name: 'Solus' }
    },
    version: {
      version: '1.2.0',
      published_at: '2026-09-01T00:00:00Z',
      content_hash: 'a'.repeat(64),
      bundle_size_bytes: 1024,
      bundle_url: '/extensions/bom/versions/1.2.0/bundle',
      manifest: fakeManifest()
    },
    enabled: true,
    settings: { refresh: 'hourly' },
    granted_scopes: ['graph.read'],
    granted_network: [],
    update_available: null,
    policy: { blocked: false, default_installed: false },
    installed_by: 'u1',
    installed_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    ...overrides
  }
}

type IndexEntries = Record<
  string,
  { version: string; source: 'registry' | 'dev'; devPath?: string }
>

export interface FakeBridge extends ExtensionsBridge {
  readonly entries: IndexEntries
}

/** A bridge whose `install` records the entry (so the post-install index read
 *  finds it) unless told to fail. */
export function fakeBridge(
  initial: IndexEntries = {},
  installResult: Awaited<ReturnType<ExtensionsBridge['install']>> = { ok: true }
): FakeBridge {
  const entries: IndexEntries = { ...initial }
  return {
    entries,
    index: vi.fn(async () => ({
      schema_version: 1 as const,
      installed: Object.fromEntries(
        Object.entries(entries).map(([id, e]) => [
          id,
          { ...e, contentHash: 'b'.repeat(64), installedAt: '2026-09-01T00:00:00Z' }
        ])
      )
    })),
    install: vi.fn(async (req) => {
      if (installResult.ok) entries[req.id] = { version: req.version, source: 'registry' }
      return installResult
    }),
    uninstall: vi.fn(async () => ({ ok: true })),
    devLoad: vi.fn(async () => ({ ok: false as const, problems: [] })),
    devRemove: vi.fn(async () => ({ ok: true })),
    openWindow: vi.fn(async () => ({ ok: true as const, created: true })),
    netFetch: vi.fn(async () => ({ ok: false as const, error: 'not_installed' as const }))
  }
}

export function fakeBundleDeps(overrides: Partial<InstalledBundleDeps> = {}): InstalledBundleDeps {
  return {
    bridge: fakeBridge({ bom: { version: '1.2.0', source: 'registry' } }),
    listInstalls: vi.fn(async () => [fakeInstall()]),
    fetchBundle: vi.fn(async () => ({ bytes: new ArrayBuffer(8), contentHash: 'a'.repeat(64) })),
    devRegistration: () => null,
    ...overrides
  }
}
