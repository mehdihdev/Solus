// SOLUSDEV-235 / EXT-12 — what every handler receives: the host's policy (the
// ONLY scope any call runs under), the extension's own settings, the injected
// deps, and the per-frame session (ready flag, event emitter, telemetry).
import type { BridgeDeps, SettingsValues } from '../bridgeDeps'
import type { BridgeEventName, BridgeMethod } from '../bridgeProtocol'
import type { ValidatedParams } from '../paramsSchema'
import type { BridgePolicy } from '../policySnapshot'
import type { TelemetryRegistry } from './telemetryRegistry'

export interface BridgeSession {
  markReady(): void
  emit(event: BridgeEventName, data: unknown): void
  readonly telemetry: TelemetryRegistry
}

export interface HandlerContext {
  readonly policy: BridgePolicy
  readonly settings: SettingsValues
  readonly deps: BridgeDeps
  readonly session: BridgeSession
}

export type Handler<M extends BridgeMethod> = (
  params: ValidatedParams[M],
  ctx: HandlerContext
) => Promise<unknown>

export type HandlerTable<M extends BridgeMethod> = { readonly [K in M]: Handler<K> }
