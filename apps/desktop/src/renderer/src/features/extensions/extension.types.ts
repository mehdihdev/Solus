// SOLUSDEV-235 — the Store's view of an extension.
//
// An extension is the UNIT THE STORE INSTALLS: a named, versioned, permissioned
// bundle that contributes widgets (CTR-01 manifests), SOL grounding, checks or
// panels to a project. This is the renderer-side shape only; the backend model
// (catalog, per-project install state, permission grants) is planned
// separately and these types are the seam it will fill. Nothing here reaches
// `packages/contracts/` — promoting it is an ADR-032 tier-2 decision.
import type { IconName } from '../../components/ui/icons.constants'

/** Who ships the extension. `solus` carries the verified badge. */
export type Publisher = 'solus' | 'community'

/** A kind of connected source an extension needs before it can do anything. */
export type SourceKind = 'code' | 'eda' | 'cad' | 'canbus' | 'runtime'

/**
 * Requirements are an AND of ORs: every group must be satisfied by at least
 * one connected kind. `[['cad', 'eda']]` reads "needs CAD or EDA";
 * `[['eda'], ['runtime']]` reads "needs EDA and runtime".
 */
export type Requirements = ReadonlyArray<ReadonlyArray<SourceKind>>

export type ContributionKind = 'widget' | 'grounding' | 'check' | 'panel'

export interface Contribution {
  readonly kind: ContributionKind
  readonly title: string
  readonly detail: string
}

/** The closed set of scopes an extension can hold. Solus code decides what a
 *  scope permits — an extension only declares which it wants (CLAUDE.md §7). */
export type PermissionScope = 'graph.read' | 'telemetry.read' | 'sources.read' | 'findings.write'

export type PermissionStatus = 'granted' | 'not_asked'

export interface Permission {
  readonly scope: PermissionScope
  readonly status: PermissionStatus
}

export interface CreditEstimate {
  /** Credits spent this billing cycle in the open project (ADR-018). */
  readonly thisCycle: number
  /** Typical per-run cost; null when the extension never calls a model. */
  readonly perRun: number | null
}

export interface ExtensionLinks {
  readonly documentation?: string
  readonly source?: string
  readonly issues?: string
}

export interface ExtensionManifest {
  /** Stable lowercase slug; appears in install state and telemetry. */
  readonly id: string
  readonly name: string
  readonly publisher: Publisher
  readonly summary: string
  readonly icon: IconName
  readonly version: string
  /** ISO timestamp of the current version's release. */
  readonly updatedAt: string
  /** Install count from the catalog service; null until the backend reports one. */
  readonly installs: number | null
  readonly requires: Requirements
  readonly contributions: readonly Contribution[]
  readonly permissions: readonly Permission[]
  readonly credits: CreditEstimate
  readonly links: ExtensionLinks
  /** Ships installed in every project (the capabilities Solus is not useful without). */
  readonly defaultInstalled: boolean
}

export type RunFrequency = 'every_sync' | 'hourly' | 'daily' | 'manual'

/** What the Store stores per project per extension. */
export interface ExtensionInstallState {
  readonly installed: boolean
  readonly enabled: boolean
  readonly runFrequency: RunFrequency
}

/** Where a card sits: installed, blocked on a missing source, or ready to install. */
export type ExtensionAvailability = 'installed' | 'needs_source' | 'available'

/** A manifest joined with the open project's state — what every Store surface renders. */
export interface ExtensionView {
  readonly manifest: ExtensionManifest
  readonly state: ExtensionInstallState
  readonly availability: ExtensionAvailability
  /** The requirement groups the project does not yet satisfy. */
  readonly missing: Requirements
}
