// SOLUSDEV-235 / EXT-12 — the host's injectable dependencies. Pure types: the
// BridgeHost dispatches every method to ONE of these seams, so the whole
// refusal/limit/validation pipeline is provable with fakes, and the real
// wiring (typed client, focus store, desktop bridge) lives in defaultDeps.ts.
import type { Focus } from '@solus/shared-types'
import type { ExtensionsBridge } from '../../../lib/desktopBridge'
import type { Entity, Neighborhood, Source } from '../../../lib/api/resources'
import type { BridgeErrorCode } from './bridgeProtocol'
import type { BridgePolicy } from './policySnapshot'

/** The preload's `solus.extensions.netFetch` shapes, derived so the renderer
 *  depends on the bridge surface only, never on main's modules. */
export type ExtNetFetchRequest = Parameters<ExtensionsBridge['netFetch']>[0]
export type ExtNetFetchResult = Awaited<ReturnType<ExtensionsBridge['netFetch']>>
export type ExtNetFetchError = Extract<ExtNetFetchResult, { ok: false }>['error']

export type SettingsValues = Readonly<Record<string, boolean | number | string>>

export interface BridgeGraphDeps {
  /** The entity under the shared focus, straight from the focus store (no request). */
  focusedEntity(): Entity | null
  getEntity(projectId: string, entityId: string): Promise<unknown>
  getNeighborhood(
    projectId: string,
    entityId: string,
    depth: number,
    limit: number
  ): Promise<Neighborhood>
  search(projectId: string, q: string, types: readonly string[], limit: number): Promise<Entity[]>
}

export interface BridgeFocusDeps {
  get(): Focus | null
  /** The host arbitrates; true when the focus moved. */
  propose(next: Focus): Promise<boolean>
}

export interface BridgeStorageDeps {
  /** Rejects with the client's ApiError on a miss (404) — the handler maps it to null. */
  get(projectId: string, slug: string, key: string): Promise<unknown>
  set(projectId: string, slug: string, key: string, value: string): Promise<void>
  delete(projectId: string, slug: string, key: string): Promise<void>
}

export interface BridgeNetDeps {
  fetch(request: ExtNetFetchRequest): Promise<ExtNetFetchResult>
}

export interface BridgeSourcesDeps {
  list(projectId: string): Promise<Source[]>
}

export interface TelemetrySample {
  readonly signalId: string
  readonly t: number
  readonly value: number
}

export interface BridgeTelemetryDeps {
  /** Resolves to the unsubscribe function. */
  subscribe(
    projectId: string,
    signalIds: readonly string[],
    onSamples: (samples: readonly TelemetrySample[]) => void
  ): Promise<() => void>
}

export interface FindingInput {
  readonly title: string
  readonly body: string
  readonly severity: string
  readonly entityIds: readonly string[]
}

export interface BridgeFindingsDeps {
  create(projectId: string, input: FindingInput): Promise<{ findingId: string }>
}

export interface SolAskInput {
  readonly policy: BridgePolicy
  readonly prompt: string
  readonly entityIds: readonly string[]
}

export interface BridgeSolDeps {
  /** The attributed turn (§6.6); resolves to the answer TEXT only. */
  ask(input: SolAskInput): Promise<string>
}

export interface BridgeUiDeps {
  /** Already validated https; goes through main's externalUrl guard. */
  openExternal(url: string): Promise<void>
}

/** The `extension.bridge_refused` data-collection event (§6.4). */
export interface BridgeRefusal {
  readonly extensionId: string
  readonly version: string
  readonly method: string
  readonly code: BridgeErrorCode
}

export interface BridgeDeps {
  readonly graph: BridgeGraphDeps
  readonly focus: BridgeFocusDeps
  readonly storage: BridgeStorageDeps
  /** Null outside Electron — `net.fetch` answers `unavailable`. */
  readonly net: BridgeNetDeps | null
  readonly sources: BridgeSourcesDeps
  /** Null until the Live Bench stream fan-out is wired — `unavailable`. */
  readonly telemetry: BridgeTelemetryDeps | null
  /** Null until a findings write route exists — `unavailable`. */
  readonly findings: BridgeFindingsDeps | null
  readonly sol: BridgeSolDeps
  readonly ui: BridgeUiDeps
  /** Current values of the app's CSS variables for `init` / `theme.changed`. */
  theme(): Readonly<Record<string, string>>
  emitRefusal(refusal: BridgeRefusal): void
}
