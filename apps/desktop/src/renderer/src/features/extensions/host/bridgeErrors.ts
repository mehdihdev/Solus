// SOLUSDEV-235 / EXT-12 — error shaping for the bridge (extensions-runtime.md
// §6.4). Messages are short fixed strings owned by the host: never a server
// body, a stack, a URL, or an id the frame did not already have.
import { ApiError } from '../../../lib/api/envelope.types'
import type { BridgeError, BridgeErrorCode } from './bridgeProtocol'

export const BRIDGE_MESSAGES: Readonly<Record<BridgeErrorCode, string>> = {
  unknown_method: 'Unknown method',
  scope_denied: 'Scope not granted',
  invalid_params: 'Invalid params',
  rate_limited: 'Too many requests',
  network_denied: 'Network target not allowed',
  blocked: 'Extension is not available in this project',
  storage_quota: 'Storage quota exceeded',
  unavailable: 'Solus is unavailable',
  internal: 'Internal error'
}

/** Thrown by handlers to refuse with a specific code (and optional fixed message). */
export class BridgeFault extends Error {
  readonly code: BridgeErrorCode

  constructor(code: BridgeErrorCode, message: string = BRIDGE_MESSAGES[code]) {
    super(message)
    this.name = 'BridgeFault'
    this.code = code
  }
}

export function bridgeError(code: BridgeErrorCode, message?: string): BridgeError {
  return { code, message: message ?? BRIDGE_MESSAGES[code] }
}

/** Route-plan `error.code` (§13) → bridge code. Unlisted codes fall to status. */
const API_CODE_MAP: Readonly<Record<string, BridgeErrorCode>> = {
  scope_denied: 'scope_denied',
  extension_blocked: 'blocked',
  storage_quota_exceeded: 'storage_quota',
  payload_too_large: 'invalid_params',
  validation_error: 'invalid_params',
  rate_limited: 'rate_limited',
  not_found: 'invalid_params'
}

function fromApiError(error: ApiError): BridgeError {
  const mapped = API_CODE_MAP[error.code]
  if (mapped) return bridgeError(mapped, error.code === 'not_found' ? 'Not found' : undefined)
  if (error.status === 403) return bridgeError('blocked')
  return bridgeError('unavailable')
}

/**
 * Anything a handler threw → the one error the frame sees. `ApiError` maps by
 * code/status; a transport failure (fetch's TypeError, an abort) is
 * `unavailable`; anything else is a host fault → `internal`.
 */
export function toBridgeError(error: unknown): BridgeError {
  if (error instanceof BridgeFault) return bridgeError(error.code, error.message)
  if (error instanceof ApiError) return fromApiError(error)
  if (error instanceof TypeError) return bridgeError('unavailable')
  if (error instanceof DOMException && error.name === 'AbortError')
    return bridgeError('unavailable')
  return bridgeError('internal')
}
