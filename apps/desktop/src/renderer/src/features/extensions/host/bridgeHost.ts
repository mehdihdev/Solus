// SOLUSDEV-235 / EXT-12 — the BridgeHost: every message in or out of ONE
// extension frame (docs/architecture/extensions-runtime.md §6). Pipeline per
// inbound message:
//
//   source check → parse (drop) → snapshot/scope (authorize) → duplicate id →
//   rate limit → param schema → handler → exactly one response
//
// Outbound messages never carry a token, a base URL, a header, or a server
// body (§3 — the frame's origin is opaque, so `postMessage` targets '*').
import type { BridgeDeps, SettingsValues } from './bridgeDeps'
import { bridgeError, toBridgeError } from './bridgeErrors'
import {
  EVENT_SCOPES,
  REFUSAL_CODES,
  parseBridgeRequest,
  type BridgeErrorCode,
  type BridgeEventName,
  type BridgeMethod,
  type BridgeOutbound,
  type BridgeRequest
} from './bridgeProtocol'
import { appHandlers } from './handlers/app'
import type { BridgeSession, Handler, HandlerContext } from './handlers/context'
import { focusHandlers } from './handlers/focus'
import { graphHandlers } from './handlers/graph'
import { netHandlers } from './handlers/net'
import { solHandlers } from './handlers/sol'
import { storageHandlers } from './handlers/storage'
import { telemetryHandlers } from './handlers/telemetry'
import { createTelemetryRegistry, type RegistryTimers } from './handlers/telemetryRegistry'
import { validateParams } from './paramsSchema'
import { authorize, type BridgePolicy } from './policySnapshot'
import { sharedRateLimiterFor, type RateLimiter } from './rateLimiter'

const HANDLERS: { readonly [M in BridgeMethod]: Handler<M> } = {
  ...appHandlers,
  ...graphHandlers,
  ...storageHandlers,
  ...netHandlers,
  ...focusHandlers,
  ...solHandlers,
  ...telemetryHandlers
}

/** The frame as the host sees it: a place to post, and the identity test. */
export interface BridgeFrame {
  postMessage(message: BridgeOutbound): void
  /** True only for the window of the frame THIS host mounted. */
  isSource(source: unknown): boolean
}

export interface BridgeMessageEvent {
  readonly origin: string
  readonly source: unknown
  readonly data: unknown
}

export interface BridgeHostOptions {
  readonly frame: BridgeFrame
  readonly policy: BridgePolicy
  readonly settings?: SettingsValues
  readonly deps: BridgeDeps
  /** Defaults to the renderer-wide per-extension limiter. */
  readonly rateLimiter?: RateLimiter
  readonly onReady?: () => void
  readonly timers?: RegistryTimers
}

export interface BridgeHost {
  /** Resolves once the message is fully handled (dropped, refused, or answered). */
  handleMessage(event: BridgeMessageEvent): Promise<void>
  /** Post the §6.2 `init` payload (after the frame's `load`). */
  init(): void
  /** Post an unsolicited event; dropped before `ui.ready` (except `init`) or without the gating scope. */
  sendEvent(event: BridgeEventName, data: unknown): void
  updatePolicy(policy: BridgePolicy): void
  /** Replace settings and notify the frame (`settings.changed`). */
  updateSettings(settings: SettingsValues): void
  isReady(): boolean
  /** Malformed messages from this frame, for the DEV badge tooltip. */
  stats(): { dropped: number }
  dispose(): void
}

function ok(id: string, result: unknown): BridgeOutbound {
  return { v: 1, id, ok: true, result }
}

function fail(id: string, code: BridgeErrorCode, message?: string): BridgeOutbound {
  return { v: 1, id, ok: false, error: bridgeError(code, message) }
}

export function createBridgeHost(options: BridgeHostOptions): BridgeHost {
  const { frame, deps } = options
  const limiter = options.rateLimiter ?? sharedRateLimiterFor(options.policy.extensionId)
  let policy = options.policy
  let settings: SettingsValues = options.settings ?? {}
  let ready = false
  let initSent = false
  let disposed = false
  let dropped = 0
  const inFlightIds = new Set<string>()

  const post = (message: BridgeOutbound): void => {
    if (!disposed) frame.postMessage(message)
  }

  function sendEvent(event: BridgeEventName, data: unknown): void {
    if (event !== 'init' && !ready) return
    const gate = EVENT_SCOPES[event]
    if (gate && !gate.some((scope) => policy.grantedScopes.includes(scope))) return
    post({ v: 1, event, data })
  }

  function init(): void {
    initSent = true
    sendEvent('init', {
      extensionId: policy.extensionId,
      version: policy.version,
      projectId: policy.projectId,
      settings: { ...settings },
      theme: deps.theme(),
      focus: deps.focus.get(),
      mode: policy.mode
    })
  }

  const telemetry = createTelemetryRegistry(
    (batch) => sendEvent('telemetry.sample', batch),
    options.timers
  )

  const session: BridgeSession = {
    markReady() {
      if (!initSent) init()
      const first = !ready
      ready = true
      if (first) options.onReady?.()
    },
    emit: sendEvent,
    telemetry
  }

  function refuse(request: BridgeRequest, code: BridgeErrorCode, message?: string): void {
    post(fail(request.id, code, message))
    if (REFUSAL_CODES.has(code)) {
      deps.emitRefusal({
        extensionId: policy.extensionId,
        version: policy.version,
        method: request.method,
        code
      })
    }
  }

  async function execute<M extends BridgeMethod>(request: BridgeRequest, method: M): Promise<void> {
    const params = validateParams(method, request.params)
    if (params === null) return refuse(request, 'invalid_params')
    const ctx: HandlerContext = { policy, settings, deps, session }
    inFlightIds.add(request.id)
    try {
      const result = await (HANDLERS[method] as Handler<M>)(params, ctx)
      post(ok(request.id, result))
    } catch (error) {
      const mapped = toBridgeError(error)
      refuse(request, mapped.code, mapped.message)
    } finally {
      inFlightIds.delete(request.id)
    }
  }

  async function dispatch(request: BridgeRequest): Promise<void> {
    const denied = authorize(policy, request.method)
    if (denied !== null) return refuse(request, denied)
    if (inFlightIds.has(request.id)) return refuse(request, 'invalid_params')
    if (limiter.tryAcquire() === 'rate_limited') return refuse(request, 'rate_limited')
    try {
      await execute(request, request.method as BridgeMethod)
    } finally {
      limiter.release()
    }
  }

  return {
    async handleMessage(event) {
      if (disposed || !frame.isSource(event.source)) return
      const request = parseBridgeRequest(event.data)
      if (request === null) {
        dropped += 1
        return
      }
      await dispatch(request)
    },
    init,
    sendEvent,
    updatePolicy(next) {
      policy = next
    },
    updateSettings(next) {
      settings = next
      sendEvent('settings.changed', { ...next })
    },
    isReady: () => ready,
    stats: () => ({ dropped }),
    dispose() {
      disposed = true
      telemetry.dispose()
    }
  }
}
