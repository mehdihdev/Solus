// SOLUSDEV-235 — pure rules over the server catalog and install rows. API rows
// + connected sources in, `ExtensionView`s out; no store, no fetch, so every
// Store surface renders the same answer and the rules are unit-testable in
// isolation. Server rows are a trust boundary (CLAUDE.md §8): source kinds and
// scopes are checked against the contract's closed sets before they are used.
import { PERMISSION_SCOPES, SOURCE_KINDS, type ExtensionManifest } from '@solus/shared-types'
import type { ApiError } from '../../lib/api/envelope.types'
import {
  extensionAssetUrl,
  type ExtensionCatalogItemApi,
  type ExtensionInstallApi
} from '../../lib/api/resources.extensions'
import type {
  Contribution,
  ExtensionAssetUrls,
  ExtensionAvailability,
  ExtensionCatalogSummary,
  ExtensionGrants,
  ExtensionInstallState,
  ExtensionSettings,
  ExtensionView,
  PermissionScope,
  Requirements,
  SourceKind
} from './extension.types'

/** Connected-source `type` (as the API reports it) → the kind extensions require. */
const SOURCE_TYPE_KIND: Readonly<Record<string, SourceKind>> = {
  github: 'code',
  gitlab: 'code',
  kicad: 'eda',
  altium: 'eda',
  onshape: 'cad',
  ros: 'runtime',
  canbus: 'canbus'
}

export const SOURCE_KIND_LABEL: Readonly<Record<SourceKind, string>> = {
  code: 'CODE',
  eda: 'EDA',
  cad: 'CAD',
  canbus: 'CANBUS',
  runtime: 'RUNTIME'
}

/** Long-form requirement names for the detail page's REQUIRES card. */
export const SOURCE_KIND_DESCRIPTION: Readonly<Record<SourceKind, string>> = {
  code: 'A code source (GitHub, GitLab)',
  eda: 'An EDA source (KiCad, Altium)',
  cad: 'A CAD source (Onshape)',
  canbus: 'A CAN bus connection',
  runtime: 'A runtime source (ROS, serial)'
}

/** Solus copy per scope (extensions-runtime wireflow §1): never text from a manifest. */
export const PERMISSION_TEXT: Readonly<Record<PermissionScope, { title: string; detail: string }>> =
  {
    'graph.read': {
      title: 'Read the workspace graph',
      detail: 'Entities, relations and neighbourhoods of this project.'
    },
    'telemetry.read': {
      title: 'Read telemetry streams',
      detail: 'Live and recorded signal values of this project.'
    },
    'sources.read': {
      title: 'List connected sources',
      detail: 'Which tools are connected and when they last synced.'
    },
    'findings.write': {
      title: 'Raise findings',
      detail: 'Add cross-domain findings to this project.'
    },
    'sol.ask': {
      title: 'Ask SOL',
      detail: 'Metered to your credits and attributed to the extension.'
    },
    'storage.own': {
      title: 'Keep its own data',
      detail: 'A private per-project key-value store, up to 256 KiB.'
    },
    'focus.read': { title: 'Read the shared focus', detail: 'Which entity is selected.' },
    'focus.write': {
      title: 'Propose a focus change',
      detail: 'Solus arbitrates before anything moves.'
    }
  }

export const NOT_INSTALLED: ExtensionInstallState = {
  installed: false,
  enabled: false,
  settings: {},
  grantedScopes: [],
  grantedNetwork: [],
  pinnedVersion: null,
  updateAvailable: null,
  blocked: false
}

const KNOWN_KINDS: ReadonlySet<string> = new Set(SOURCE_KINDS)
const KNOWN_SCOPES: ReadonlySet<string> = new Set(PERMISSION_SCOPES)

function isSourceKind(value: unknown): value is SourceKind {
  return typeof value === 'string' && KNOWN_KINDS.has(value)
}

function isScope(value: unknown): value is PermissionScope {
  return typeof value === 'string' && KNOWN_SCOPES.has(value)
}

/** Requirement groups from a server row: only contract kinds, no empty groups. */
export function toRequirements(raw: unknown): Requirements {
  if (!Array.isArray(raw)) return []
  return raw
    .map((group) => (Array.isArray(group) ? group.filter(isSourceKind) : []))
    .filter((group) => group.length > 0)
}

/** The distinct source kinds a project's connected sources provide. Unknown types are ignored. */
export function connectedKinds(sourceTypes: readonly string[]): ReadonlySet<SourceKind> {
  const kinds = new Set<SourceKind>()
  for (const type of sourceTypes) {
    const kind = SOURCE_TYPE_KIND[type]
    if (kind) kinds.add(kind)
  }
  return kinds
}

/** The requirement groups none of `connected` satisfies. Empty means all met. */
export function missingRequirements(
  requires: Requirements,
  connected: ReadonlySet<SourceKind>
): Requirements {
  return requires.filter((group) => !group.some((kind) => connected.has(kind)))
}

/** "NEEDS CAD|EDA" style label for a set of unmet groups; ORs join with `|`, ANDs with `+`. */
export function requirementLabel(groups: Requirements): string {
  return groups.map((group) => group.map((k) => SOURCE_KIND_LABEL[k]).join('|')).join(' + ')
}

export function availabilityOf(
  state: ExtensionInstallState,
  missing: Requirements,
  blocked: boolean
): ExtensionAvailability {
  if (state.installed) return 'installed'
  if (blocked) return 'blocked'
  return missing.length > 0 ? 'needs_source' : 'available'
}

/** The install row (§6.1) → the Store's per-project state. */
export function installStateOf(row: ExtensionInstallApi): ExtensionInstallState {
  return {
    installed: true,
    enabled: row.enabled,
    settings: row.settings ?? {},
    grantedScopes: (row.granted_scopes ?? []).filter(isScope),
    grantedNetwork: (row.granted_network ?? []).filter((o) => typeof o === 'string'),
    pinnedVersion: row.version.version,
    updateAvailable: row.update_available
      ? {
          version: row.update_available.version,
          widensPermissions: row.update_available.widens_permissions
        }
      : null,
    blocked: row.policy?.blocked ?? false
  }
}

/** Store-facing asset routes derived from the manifest's declared paths. */
export function assetUrlsOf(
  slug: string,
  version: string,
  manifest: ExtensionManifest | null
): ExtensionAssetUrls {
  if (!manifest) return { icon: null, privacyPolicy: null }
  const icon = manifest.views.page?.icon
  const policy = manifest.store.privacy_policy
  return {
    icon: icon ? extensionAssetUrl(slug, version, icon) : null,
    privacyPolicy: policy ? extensionAssetUrl(slug, version, policy) : null
  }
}

/** The catalog row (§4.1) → the summary every card renders. */
export function catalogSummaryOf(item: ExtensionCatalogItemApi): ExtensionCatalogSummary {
  return {
    slug: item.slug,
    name: item.name,
    summary: item.summary,
    publisher: item.publisher?.display_name ?? '',
    verified: item.verified === true,
    installCount: typeof item.install_count === 'number' ? item.install_count : null,
    latestVersion: item.latest_version.version,
    updatedAt: item.updated_at,
    requires: toRequirements(item.requires),
    views: Array.isArray(item.views) ? item.views.filter((v) => typeof v === 'string') : [],
    assetUrls: { icon: null, privacyPolicy: null },
    inCatalog: true
  }
}

/** A summary for an install whose version is no longer listed (wireflow §5). */
function summaryFromInstall(row: ExtensionInstallApi): ExtensionCatalogSummary {
  const { manifest } = row.version
  return {
    slug: row.extension.slug,
    name: row.extension.name,
    summary: manifest.extension.summary,
    publisher: row.extension.publisher?.display_name ?? manifest.extension.publisher,
    verified: row.extension.verified === true,
    installCount: null,
    latestVersion: row.version.version,
    updatedAt: row.updated_at,
    requires: toRequirements(manifest.extension.requires),
    views: Object.keys(manifest.views),
    assetUrls: assetUrlsOf(row.extension.slug, row.version.version, manifest),
    inCatalog: false
  }
}

export interface ViewInputs {
  readonly catalog: ExtensionCatalogSummary
  readonly manifest: ExtensionManifest | null
  readonly state: ExtensionInstallState
  readonly connected: ReadonlySet<SourceKind>
  readonly blocked: boolean
}

export function buildView(inputs: ViewInputs): ExtensionView {
  const { catalog, manifest, state, connected, blocked } = inputs
  const missing = missingRequirements(catalog.requires, connected)
  const version = state.pinnedVersion ?? catalog.latestVersion
  return {
    catalog: { ...catalog, assetUrls: assetUrlsOf(catalog.slug, version, manifest) },
    manifest,
    state,
    availability: availabilityOf(state, missing, blocked || state.blocked),
    missing
  }
}

export interface ViewsInputs {
  readonly catalog: readonly ExtensionCatalogItemApi[]
  readonly installs: readonly ExtensionInstallApi[]
  /** Fetched details (§4.2 manifests) for extensions not installed here. */
  readonly details: Readonly<Record<string, ExtensionManifest>>
  readonly connected: ReadonlySet<SourceKind>
  /** Slugs the server refused with `extension_blocked`. */
  readonly blocked: ReadonlySet<string>
}

/** Catalog order first (the server sorts by name), then installs the catalog
 *  no longer lists. The manifest is the PINNED one for an install. */
export function buildViews(inputs: ViewsInputs): ExtensionView[] {
  const bySlug = new Map(inputs.installs.map((row) => [row.extension.slug, row]))
  const listed = inputs.catalog.map((item) => {
    const row = bySlug.get(item.slug)
    return buildView({
      catalog: catalogSummaryOf(item),
      manifest: row ? row.version.manifest : (inputs.details[item.slug] ?? null),
      state: row ? installStateOf(row) : NOT_INSTALLED,
      connected: inputs.connected,
      blocked: inputs.blocked.has(item.slug)
    })
  })
  const listedSlugs = new Set(inputs.catalog.map((item) => item.slug))
  const withdrawn = inputs.installs
    .filter((row) => !listedSlugs.has(row.extension.slug))
    .map((row) =>
      buildView({
        catalog: summaryFromInstall(row),
        manifest: row.version.manifest,
        state: installStateOf(row),
        connected: inputs.connected,
        blocked: false
      })
    )
  return [...listed, ...withdrawn]
}

/** Installed first (catalog order), then everything else — the Store's two sections. */
export function partitionViews(views: readonly ExtensionView[]): {
  installed: ExtensionView[]
  popular: ExtensionView[]
} {
  return {
    installed: views.filter((v) => v.state.installed),
    popular: views.filter((v) => !v.state.installed)
  }
}

function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? '' : 's'}`
}

const VIEW_DETAIL = {
  widget: 'A Live Bench widget on the project canvas.',
  page: 'A full-page view in the rail.',
  window: 'Opens in its own window.'
} as const

/** WHAT IT ADDS rows: only the views the manifest really declares, plus a
 *  permissions summary. Before the manifest is loaded, the catalog's view
 *  kinds stand in without labels. */
export function contributionsOf(view: ExtensionView): Contribution[] {
  const { manifest } = view
  if (!manifest) {
    return view.catalog.views
      .filter((kind): kind is keyof typeof VIEW_DETAIL => kind in VIEW_DETAIL)
      .map((kind) => ({
        kind,
        title: kind.charAt(0).toUpperCase() + kind.slice(1),
        detail: VIEW_DETAIL[kind]
      }))
  }
  const rows: Contribution[] = []
  if (manifest.views.widget)
    rows.push({ kind: 'widget', title: 'Widget', detail: VIEW_DETAIL.widget })
  if (manifest.views.page)
    rows.push({
      kind: 'page',
      title: `Page: ${manifest.views.page.label}`,
      detail: VIEW_DETAIL.page
    })
  if (manifest.views.window)
    rows.push({
      kind: 'window',
      title: `Window: ${manifest.views.window.title}`,
      detail: VIEW_DETAIL.window
    })
  const { scopes, network } = manifest.permissions
  const detail =
    scopes.length + network.length === 0
      ? 'Asks for nothing'
      : `${plural(scopes.length, 'scope')} · ${plural(network.length, 'network origin')}`
  rows.push({ kind: 'permissions', title: 'Permissions', detail })
  const backend = firstPartyDetail(manifest)
  if (backend) rows.push({ kind: 'backend', title: 'Runs in Solus (first-party)', detail: backend })
  return rows
}

/** True when the manifest declares a first-party table (ADR-035 as amended
 *  2026-09-05): its backend is in-repo Solus code, reviewed like any other. */
export function isFirstParty(manifest: ExtensionManifest | null): boolean {
  if (!manifest) return false
  return (
    manifest.backend !== undefined ||
    manifest.graph.kinds.length > 0 ||
    manifest.tools.names.length > 0
  )
}

/** "Backend routes · 1 graph kind · 2 SOL tools" — what the in-repo code provides. */
export function firstPartyDetail(manifest: ExtensionManifest): string | null {
  if (!isFirstParty(manifest)) return null
  const parts: string[] = []
  if (manifest.backend?.routes) parts.push('backend routes')
  if (manifest.graph.kinds.length > 0) parts.push(plural(manifest.graph.kinds.length, 'graph kind'))
  if (manifest.tools.names.length > 0) parts.push(plural(manifest.tools.names.length, 'SOL tool'))
  const what = parts.length > 0 ? parts.join(' · ') : 'first-party code'
  return `${what} — implemented and reviewed inside Solus, never shipped in the bundle.`
}

/** The whole declared set — grants are all-or-nothing in this build. */
export function declaredGrants(manifest: ExtensionManifest): ExtensionGrants {
  return { scopes: [...manifest.permissions.scopes], network: [...manifest.permissions.network] }
}

/** The additions a `409 grants_required` names (`details[0]`), validated. */
export function grantsRequiredOf(error: ApiError): ExtensionGrants {
  const first = error.details?.[0]
  if (typeof first !== 'object' || first === null) return { scopes: [], network: [] }
  const { scopes, network } = first as { scopes?: unknown; network?: unknown }
  return {
    scopes: Array.isArray(scopes) ? scopes.filter(isScope) : [],
    network: Array.isArray(network) ? network.filter((o) => typeof o === 'string') : []
  }
}

/** Stored values over manifest defaults, restricted to declared keys. */
export function settingValuesOf(
  manifest: ExtensionManifest,
  stored: ExtensionSettings
): ExtensionSettings {
  const out: Record<string, boolean | number | string> = {}
  for (const field of manifest.settings.fields) {
    const value = stored[field.key] ?? field.default
    if (value !== undefined) out[field.key] = value
  }
  return out
}

/** Header meta line: "Solus · v1.0.0 · — installs · updated 2w ago". */
export function installsLabel(installs: number | null): string {
  if (installs === null) return '— installs'
  return `${installs.toLocaleString()} ${installs === 1 ? 'install' : 'installs'}`
}

/** External links become anchors only when they are https — manifests are
 *  developer input, so this is the boundary every server-sourced URL crosses. */
export function isSafeExternalUrl(url: string | undefined): url is string {
  if (!url) return false
  try {
    return new URL(url).protocol === 'https:'
  } catch {
    return false
  }
}
