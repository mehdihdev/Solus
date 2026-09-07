// SOLUSDEV-235 — the Store's view of an extension.
//
// An extension is the UNIT THE STORE INSTALLS: a named, versioned, permissioned
// bundle described by its `extension.toml` manifest (the ADR-035 contract in
// @solus/shared-types). The catalog and the per-project install state come
// from the server (docs/api/extensions.md §4 / §6); this module is the
// renderer-side join every Store surface renders. Nothing here reaches
// `packages/contracts/` — the manifest shape is imported, never redeclared.
import type { ExtensionManifest, PermissionScope, SourceKind } from '@solus/shared-types'

export type { ExtensionManifest, PermissionScope, SourceKind }

/**
 * Requirements are an AND of ORs: every group must be satisfied by at least
 * one connected kind. `[['cad', 'eda']]` reads "needs CAD or EDA";
 * `[['eda'], ['runtime']]` reads "needs EDA and runtime".
 */
export type Requirements = ReadonlyArray<ReadonlyArray<SourceKind>>

/** A setting value as the API stores it (`ExtensionSettingsValuesApi`). */
export type ExtensionSettingValue = boolean | number | string
export type ExtensionSettings = Readonly<Record<string, ExtensionSettingValue>>

/** What the user granted, all-or-nothing per the wireflow's permissions step. */
export interface ExtensionGrants {
  readonly scopes: readonly PermissionScope[]
  readonly network: readonly string[]
}

/** Store-facing asset routes (relative API paths — never storage locators). */
export interface ExtensionAssetUrls {
  readonly icon: string | null
  readonly privacyPolicy: string | null
}

/** The catalog row (§4.1) — or, for an install whose version left the
 *  catalog, the same fields recovered from the install row (§6.1). */
export interface ExtensionCatalogSummary {
  /** The manifest `extension.id`; every route addresses the extension by it. */
  readonly slug: string
  readonly name: string
  readonly summary: string
  readonly publisher: string
  readonly verified: boolean
  /** Aggregate install count; null when the catalog did not report one. */
  readonly installCount: number | null
  readonly latestVersion: string
  /** ISO timestamp of the latest approved version. */
  readonly updatedAt: string
  readonly requires: Requirements
  /** The `[views]` keys the latest version declares (`widget | page | window`). */
  readonly views: readonly string[]
  readonly assetUrls: ExtensionAssetUrls
  /** False when the extension is installed here but no longer listed. */
  readonly inCatalog: boolean
}

export interface ExtensionUpdate {
  readonly version: string
  /** The newer version declares scopes or origins beyond the current grants. */
  readonly widensPermissions: boolean
}

/** The per-project install row (§6.1), or `NOT_INSTALLED` when there is none. */
export interface ExtensionInstallState {
  readonly installed: boolean
  readonly enabled: boolean
  readonly settings: ExtensionSettings
  readonly grantedScopes: readonly PermissionScope[]
  readonly grantedNetwork: readonly string[]
  readonly pinnedVersion: string | null
  readonly updateAvailable: ExtensionUpdate | null
  /** Team policy blocks this extension (server reports it disabled). */
  readonly blocked: boolean
}

/** Where a card sits: installed, blocked by the team, blocked on a missing
 *  source, or ready to install. */
export type ExtensionAvailability = 'installed' | 'blocked' | 'needs_source' | 'available'

/** A catalog entry joined with the open project's state — what every Store
 *  surface renders. `manifest` is the PINNED version's for an install and the
 *  latest approved version's otherwise; it is null until the detail has been
 *  fetched for an extension that is not installed here. */
export interface ExtensionView {
  readonly catalog: ExtensionCatalogSummary
  readonly manifest: ExtensionManifest | null
  readonly state: ExtensionInstallState
  readonly availability: ExtensionAvailability
  /** The requirement groups the project does not yet satisfy. */
  readonly missing: Requirements
}

/** One row of the Overview's WHAT IT ADDS list, derived from `manifest.views`. */
export interface Contribution {
  readonly kind: 'widget' | 'page' | 'window' | 'permissions' | 'backend'
  readonly title: string
  readonly detail: string
}
