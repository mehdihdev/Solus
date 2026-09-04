// SOLUSDEV-235 / EXT-13 — what to mount for (project, slug): the resolver
// behind useInstalledBundle, kept React-free so every branch is a plain
// async test. Truth comes from two places and is combined in a fixed order
// (extensions-runtime.md §4 "the server is the source of truth", §7 dev mode):
//
//   dev registration (renderer-held manifest + session grants, index `dev`)
//     → server install row (pinned version, manifest, grants, enabled, policy)
//       → local cache (index.json via the desktop bridge); missing → download
//         the zip and hand it to main's installer ONCE, then re-read the index.
import type { ExtensionManifest, PermissionScope } from '@solus/shared-types'
import type { ExtensionsBridge } from '../../../lib/desktopBridge'
import type {
  ExtensionBundle,
  ExtensionInstallApi,
  ExtensionSettingsValuesApi
} from '../../../lib/api/resources.extensions'
import { policyFromInstall, storeLinksOf, type BridgePolicy } from '../host/policySnapshot'
import { DEV_VERSION } from './extUrl'

export type BundleView = 'widget' | 'page' | 'window'

/** A developer-mode registration as the renderer holds it (§7): the manifest
 *  main validated and the grants the user accepted for this session. */
export interface DevRegistration {
  readonly manifest: ExtensionManifest
  readonly grantedScopes: readonly PermissionScope[]
  readonly grantedNetwork: readonly string[]
}

/** Which step failed — the page screen's error copy names it (wireflow §2). */
export type BundleErrorStep =
  | 'no_desktop'
  | 'install_lookup'
  | 'missing_view'
  | 'bad_entry'
  | 'download'
  | 'hash_mismatch'
  | 'rejected'

export interface ReadyBundle {
  readonly status: 'ready'
  readonly policy: BridgePolicy
  readonly version: string
  readonly manifest: ExtensionManifest
  /** The entry for the requested view, already contract-shaped. */
  readonly entry: string
  readonly name: string
  readonly settings: ExtensionSettingsValuesApi
  /** Null for a developer registration (no registry row → no publisher). */
  readonly publisher: { readonly displayName: string; readonly verified: boolean } | null
}

export type InstalledBundleState =
  | { readonly status: 'loading' }
  | { readonly status: 'not_installed' }
  | { readonly status: 'caching'; readonly name: string }
  | ReadyBundle
  | { readonly status: 'blocked'; readonly name: string }
  | { readonly status: 'disabled'; readonly name: string }
  | { readonly status: 'error'; readonly step: BundleErrorStep; readonly message: string }

/** What the resolver reads through, all injectable. */
export interface InstalledBundleDeps {
  /** Null outside Electron — extensions cannot run there. */
  readonly bridge: ExtensionsBridge | null
  listInstalls(projectId: string): Promise<readonly ExtensionInstallApi[]>
  fetchBundle(slug: string, version: string): Promise<ExtensionBundle>
  /** The session's developer registration for `slug`, if any (§7). */
  devRegistration(slug: string): DevRegistration | null
}

export const NO_DESKTOP_MESSAGE = 'Extensions run in the Solus desktop app.'

const error = (step: BundleErrorStep, message: string): InstalledBundleState => ({
  status: 'error',
  step,
  message
})

function entryFor(manifest: ExtensionManifest, view: BundleView): string | null {
  return manifest.views[view]?.entry ?? null
}

function readyFromDev(
  slug: string,
  projectId: string,
  view: BundleView,
  dev: DevRegistration
): InstalledBundleState {
  const entry = entryFor(dev.manifest, view)
  const name = dev.manifest.extension.name
  if (entry === null) return error('missing_view', `${name} has no ${view} view.`)
  return {
    status: 'ready',
    policy: {
      extensionId: slug,
      version: DEV_VERSION,
      projectId,
      grantedScopes: [...dev.grantedScopes],
      grantedNetwork: [...dev.grantedNetwork],
      storeLinks: storeLinksOf(dev.manifest),
      enabled: true,
      blocked: false,
      mode: 'dev'
    },
    version: DEV_VERSION,
    manifest: dev.manifest,
    entry,
    name,
    settings: {},
    publisher: null
  }
}

function readyFromInstall(
  install: ExtensionInstallApi,
  projectId: string,
  view: BundleView
): InstalledBundleState {
  const name = install.extension.name
  const entry = entryFor(install.version.manifest, view)
  if (entry === null) return error('missing_view', `${name} has no ${view} view.`)
  return {
    status: 'ready',
    policy: policyFromInstall(install, projectId, view),
    version: install.version.version,
    manifest: install.version.manifest,
    entry,
    name,
    settings: install.settings,
    publisher: {
      displayName: install.extension.publisher.display_name,
      verified: install.extension.verified
    }
  }
}

/** §8 copy for a failed download or install; `name` is the manifest's, rendered as text. */
export function installFailureState(
  name: string,
  failure: 'download' | 'hash_mismatch' | 'rejected'
): InstalledBundleState {
  switch (failure) {
    case 'download':
      return error('download', `Couldn't download ${name}.`)
    case 'hash_mismatch':
      return error('hash_mismatch', "The downloaded bundle didn't match the registry.")
    default:
      return error('rejected', "This version's bundle was rejected.")
  }
}

async function isCached(bridge: ExtensionsBridge, slug: string, version: string): Promise<boolean> {
  const index = await bridge.index()
  const entry = index.installed[slug]
  return entry !== undefined && entry.source === 'registry' && entry.version === version
}

/** Download + install once. Resolves to the failure kind, or null on success. */
async function cacheBundle(
  deps: InstalledBundleDeps,
  bridge: ExtensionsBridge,
  install: ExtensionInstallApi
): Promise<'download' | 'hash_mismatch' | 'rejected' | null> {
  const { slug } = install.extension
  const { version } = install.version
  let bundle: ExtensionBundle
  try {
    bundle = await deps.fetchBundle(slug, version)
  } catch {
    return 'download'
  }
  const result = await bridge.install({
    id: slug,
    version,
    contentHash: bundle.contentHash,
    bytes: bundle.bytes
  })
  if (result.ok) return (await isCached(bridge, slug, version)) ? null : 'rejected'
  return result.error === 'hash_mismatch' ? 'hash_mismatch' : 'rejected'
}

export interface ResolveInput {
  readonly projectId: string
  readonly slug: string
  readonly view: BundleView
}

/**
 * Resolve the mountable state, reporting `caching` through `onProgress` when a
 * download starts so the UI can say "Downloading <name>…" honestly (§8).
 */
export async function resolveInstalledBundle(
  input: ResolveInput,
  deps: InstalledBundleDeps,
  onProgress: (state: InstalledBundleState) => void = () => undefined
): Promise<InstalledBundleState> {
  const { projectId, slug, view } = input
  const { bridge } = deps
  if (bridge === null) return error('no_desktop', NO_DESKTOP_MESSAGE)
  const dev = deps.devRegistration(slug)
  if (dev !== null) return readyFromDev(slug, projectId, view, dev)

  let installs: readonly ExtensionInstallApi[]
  try {
    installs = await deps.listInstalls(projectId)
  } catch {
    return error('install_lookup', "Couldn't check what this project has installed.")
  }
  const install = installs.find((row) => row.extension.slug === slug)
  if (install === undefined) return { status: 'not_installed' }
  const name = install.extension.name
  if (install.policy.blocked) return { status: 'blocked', name }
  if (!install.enabled) return { status: 'disabled', name }

  if (!(await isCached(bridge, slug, install.version.version))) {
    onProgress({ status: 'caching', name })
    const failure = await cacheBundle(deps, bridge, install)
    if (failure !== null) return installFailureState(name, failure)
  }
  return readyFromInstall(install, projectId, view)
}
