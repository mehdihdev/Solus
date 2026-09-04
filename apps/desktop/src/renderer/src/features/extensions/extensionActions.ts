// SOLUSDEV-235 — the Store's write paths, over the typed client (docs/api/
// extensions.md §6) and the desktop bundle cache (`solus.extensions`). Each
// action does the server write FIRST — the server is the record — then the
// machine-local step, and reports what happened instead of pretending: a
// bundle that could not be cached is a note on a successful install, never a
// fabricated failure or a silent success.
import type { ExtensionsBridge } from '../../lib/desktopBridge'
import { ApiError } from '../../lib/api/envelope.types'
import {
  fetchExtensionBundle,
  getExtension,
  installExtension,
  patchExtensionInstall,
  uninstallProjectExtension,
  type ExtensionInstallApi
} from '../../lib/api/resources.extensions'
import type { ExtensionManifest } from '@solus/shared-types'
import type { ExtensionGrants, ExtensionSettings } from './extension.types'
import {
  BUNDLE_DEFERRED_NOTE,
  bundleFailureNote,
  describeExtensionError,
  type ExtensionFailure
} from './extensionErrors'
import { grantsRequiredOf } from './extensionLogic'

export type BundleOutcome = 'cached' | 'deferred' | 'failed'

export type ExtensionActionResult =
  | { readonly ok: true; readonly bundle?: BundleOutcome; readonly note?: string }
  | (ExtensionFailure & { readonly ok: false; readonly grantsRequired?: ExtensionGrants })

export interface ExtensionActions {
  /** Grant the given set and install the catalog's latest version. */
  install: (slug: string, grants: ExtensionGrants) => Promise<ExtensionActionResult>
  /** Move the pin to the available update; `grants` widens the current set
   *  after a `grants_required` answer. */
  update: (slug: string, grants?: ExtensionGrants) => Promise<ExtensionActionResult>
  uninstall: (slug: string) => Promise<ExtensionActionResult>
  setEnabled: (slug: string, enabled: boolean) => Promise<ExtensionActionResult>
  setSettings: (slug: string, values: ExtensionSettings) => Promise<ExtensionActionResult>
  /** Fetch the catalog detail (§4.2) so an uninstalled extension has a manifest. */
  loadDetail: (slug: string) => Promise<void>
  refresh: () => Promise<void>
}

/** What the hook lends the actions: the latest rows and the state setters. */
export interface ExtensionActionDeps {
  readonly projectId: string
  readonly bridge: () => ExtensionsBridge | null
  readonly latestVersionOf: (slug: string) => string | undefined
  readonly installOf: (slug: string) => ExtensionInstallApi | undefined
  readonly applyInstall: (row: ExtensionInstallApi) => void
  readonly removeInstall: (slug: string) => void
  readonly markBlocked: (slug: string) => void
  readonly applyDetail: (slug: string, manifest: ExtensionManifest) => void
  readonly refresh: () => Promise<void>
}

function failure(error: unknown): ExtensionActionResult {
  return { ok: false, ...describeExtensionError(error) }
}

/** Download the pinned bundle and hand it to main, which verifies the hash
 *  before caching (§4.4). Runs AFTER the server row exists, so every outcome
 *  here is a note on a successful install. */
async function cacheBundle(
  bridge: ExtensionsBridge | null,
  row: ExtensionInstallApi
): Promise<ExtensionActionResult> {
  if (!bridge) return { ok: true, bundle: 'deferred', note: BUNDLE_DEFERRED_NOTE }
  const { slug } = row.extension
  const { version, content_hash } = row.version
  try {
    const bundle = await fetchExtensionBundle(slug, version)
    if (bundle.contentHash !== content_hash) {
      return { ok: true, bundle: 'failed', note: bundleFailureNote('hash_mismatch') }
    }
    const result = await bridge.install({
      id: slug,
      version,
      contentHash: bundle.contentHash,
      bytes: bundle.bytes
    })
    if (!result.ok) return { ok: true, bundle: 'failed', note: bundleFailureNote(result.error) }
    return { ok: true, bundle: 'cached' }
  } catch (error) {
    return {
      ok: true,
      bundle: 'failed',
      note: bundleFailureNote(describeExtensionError(error).code)
    }
  }
}

async function putInstall(
  deps: ExtensionActionDeps,
  slug: string,
  version: string,
  grants: ExtensionGrants
): Promise<ExtensionActionResult> {
  let row: ExtensionInstallApi
  try {
    row = await installExtension(deps.projectId, slug, {
      version,
      grants: { scopes: [...grants.scopes], network: [...grants.network] }
    })
  } catch (error) {
    if (error instanceof ApiError && error.code === 'extension_blocked') deps.markBlocked(slug)
    if (error instanceof ApiError && error.code === 'grants_required') {
      return { ...failure(error), grantsRequired: grantsRequiredOf(error) } as ExtensionActionResult
    }
    return failure(error)
  }
  deps.applyInstall(row)
  return cacheBundle(deps.bridge(), row)
}

async function patch(
  deps: ExtensionActionDeps,
  slug: string,
  body: Parameters<typeof patchExtensionInstall>[2]
): Promise<ExtensionActionResult> {
  try {
    deps.applyInstall(await patchExtensionInstall(deps.projectId, slug, body))
    return { ok: true }
  } catch (error) {
    return failure(error)
  }
}

export function createExtensionActions(deps: ExtensionActionDeps): ExtensionActions {
  return {
    install: (slug, grants) => {
      const version = deps.latestVersionOf(slug)
      if (!version) return Promise.resolve(failure(new ApiError(404, 'not_found', 'not listed')))
      return putInstall(deps, slug, version, grants)
    },

    update: (slug, grants) => {
      const row = deps.installOf(slug)
      const target = row?.update_available?.version
      if (!row || !target) {
        return Promise.resolve({
          ok: false,
          code: 'no_update',
          message: 'Nothing newer to install.'
        })
      }
      const current = grants ?? { scopes: row.granted_scopes, network: row.granted_network }
      return putInstall(deps, slug, target, current)
    },

    uninstall: async (slug) => {
      try {
        await uninstallProjectExtension(deps.projectId, slug)
      } catch (error) {
        return failure(error)
      }
      deps.removeInstall(slug)
      const bridge = deps.bridge()
      if (!bridge) return { ok: true }
      const result = await bridge.uninstall(slug).catch(() => ({ ok: false }))
      return result.ok
        ? { ok: true }
        : {
            ok: true,
            note: 'Uninstalled here; the cached bundle could not be removed from this machine.'
          }
    },

    setEnabled: (slug, enabled) => patch(deps, slug, { enabled }),
    setSettings: (slug, values) => patch(deps, slug, { settings: { ...values } }),

    loadDetail: async (slug) => {
      try {
        const detail = await getExtension(slug)
        if (detail.manifest) deps.applyDetail(slug, detail.manifest)
      } catch {
        // The detail is a convenience over the catalog row; the card and the
        // header keep rendering from the list, and the tabs say it is loading.
      }
    },

    refresh: deps.refresh
  }
}
