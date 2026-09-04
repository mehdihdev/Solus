// SOLUSDEV-235 / EXT-12 — the install+policy snapshot (extensions-runtime.md
// §6.8) as the host holds it for ONE mounted extension, and the check every
// bridge call passes before anything else runs. Scope comes from here, never
// from the message (§3): the policy names the project; a request cannot.
import type { ExtensionManifest, PermissionScope } from '@solus/shared-types'
import type { ExtensionInstallApi } from '../../../lib/api/resources.extensions'
import {
  METHOD_SCOPES,
  SERVER_ATTRIBUTED_METHODS,
  isKnownMethod,
  type BridgeErrorCode
} from './bridgeProtocol'

/** `dev` is reported for any developer registration regardless of view kind (§6.2). */
export type BridgeMode = 'widget' | 'page' | 'window' | 'dev'

export interface BridgePolicy {
  readonly extensionId: string
  /** semver, or `dev` */
  readonly version: string
  /** The HOST's project — the only scope any call runs under. */
  readonly projectId: string
  readonly grantedScopes: readonly PermissionScope[]
  /** https origins the user granted; `net.fetch` targets must match exactly. */
  readonly grantedNetwork: readonly string[]
  /** The manifest's `store.links` values verbatim — the only URLs
   *  `ui.openExternal` may open outside the granted origins (SEC-C1). */
  readonly storeLinks?: readonly string[]
  readonly enabled: boolean
  readonly blocked: boolean
  readonly mode: BridgeMode
}

/**
 * The §6.8 gate, then §6.3/§6.4: `blocked` for a disabled or team-blocked
 * install, `unknown_method` off the table, `blocked` for server-attributed
 * methods in dev mode (no install row exists for the server to verify — §10),
 * `scope_denied` for an ungranted scope. Null means proceed to validation.
 */
export function authorize(policy: BridgePolicy, method: string): BridgeErrorCode | null {
  if (policy.blocked || !policy.enabled) return 'blocked'
  if (!isKnownMethod(method)) return 'unknown_method'
  if (policy.mode === 'dev' && SERVER_ATTRIBUTED_METHODS.has(method)) return 'blocked'
  const required = METHOD_SCOPES[method]
  if (required !== null && !policy.grantedScopes.includes(required)) return 'scope_denied'
  return null
}

/** The `store.links` values a manifest declares, as exact URLs. */
export function storeLinksOf(manifest: ExtensionManifest): readonly string[] {
  return Object.values(manifest.store.links).filter((v): v is string => typeof v === 'string')
}

/** A §6.1 install row → the policy for a frame mounted in `projectId`. A team
 *  block is reported with `enabled: false` server-side already; mirrored here
 *  so a stale row can only refuse, never over-permit. */
export function policyFromInstall(
  install: ExtensionInstallApi,
  projectId: string,
  mode: Exclude<BridgeMode, 'dev'>
): BridgePolicy {
  const blocked = install.policy.blocked
  return {
    extensionId: install.extension.slug,
    version: install.version.version,
    projectId,
    grantedScopes: [...install.granted_scopes],
    grantedNetwork: [...install.granted_network],
    storeLinks: storeLinksOf(install.version.manifest),
    enabled: install.enabled && !blocked,
    blocked,
    mode
  }
}
