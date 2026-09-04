// SOLUSDEV-235 / EXT-12 — `net.fetch` (§6.3, §6.5). The host decides https +
// granted origin BEFORE anything crosses to main (which re-checks against the
// cached manifest and does the SSRF work); the response comes back as text
// when the content-type is textual, else base64.
import type { ExtNetFetchError } from '../bridgeDeps'
import { BridgeFault } from '../bridgeErrors'
import type { BridgeErrorCode } from '../bridgeProtocol'
import { isGrantedOrigin } from '../originAllow'
import type { HandlerTable } from './context'

const TEXTUAL_RE =
  /^(text\/|application\/(json|xml|javascript|x-www-form-urlencoded)|[^;]*\+(json|xml))/i

export function utf8ToBase64(text: string): string {
  const bytes = new TextEncoder().encode(text)
  let binary = ''
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  }
  return btoa(binary)
}

export function base64ToBytes(base64: string): Uint8Array {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes
}

export interface DecodedBody {
  readonly body: string
  readonly encoding: 'text' | 'base64'
}

export function decodeNetBody(bodyBase64: string, contentType: string | undefined): DecodedBody {
  if (contentType !== undefined && TEXTUAL_RE.test(contentType)) {
    return { body: new TextDecoder().decode(base64ToBytes(bodyBase64)), encoding: 'text' }
  }
  return { body: bodyBase64, encoding: 'base64' }
}

/** Main's refusal → the frame's code, with the §6.5 message where it names one. */
const NET_FAULTS: Readonly<Record<ExtNetFetchError, [BridgeErrorCode, string?]>> = {
  scheme_not_https: ['network_denied'],
  origin_not_allowed: ['network_denied'],
  address_refused: ['network_denied'],
  redirect_refused: ['network_denied'],
  method_not_allowed: ['network_denied'],
  response_too_large: ['network_denied', 'response too large'],
  request_too_large: ['invalid_params'],
  invalid_input: ['invalid_params'],
  not_installed: ['blocked'],
  unauthorized: ['unavailable'],
  timeout: ['unavailable'],
  network_error: ['unavailable'],
  dns_failed: ['unavailable']
}

function netFault(error: ExtNetFetchError): BridgeFault {
  const [code, message] = NET_FAULTS[error] ?? ['unavailable']
  return new BridgeFault(code, message)
}

export const netHandlers: HandlerTable<'net.fetch'> = {
  'net.fetch': async (p, ctx) => {
    // SEC-C1: the ONE allowlist predicate (originAllow.ts) — https + exact origin.
    if (!isGrantedOrigin(ctx.policy, p.url)) throw new BridgeFault('network_denied')
    if (!ctx.deps.net) throw new BridgeFault('unavailable')
    const result = await ctx.deps.net.fetch({
      id: ctx.policy.extensionId,
      url: p.url,
      method: p.method,
      headers: { ...p.headers },
      ...(p.body === undefined ? {} : { bodyBase64: utf8ToBase64(p.body) }),
      allowedOrigins: [...ctx.policy.grantedNetwork]
    })
    if (!result.ok) throw netFault(result.error)
    return {
      status: result.status,
      headers: result.headers,
      ...decodeNetBody(result.bodyBase64, result.headers['content-type'])
    }
  }
}
