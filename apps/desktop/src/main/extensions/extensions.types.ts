// SOLUSDEV-235 / EXT-05 — the `solus.extensions` preload surface, typed once
// here and consumed by main (extensionsIpc.ts), preload (index.ts) and the
// renderer (lib/desktopBridge.ts re-exports it). Pure types: no runtime import.
import type { ExtensionManifest } from '@solus/shared-types'
import type { InstallError } from './bundleInstall'
import type { ExtensionIndex } from './extensionIndex'
import type { NetFetchError, NetFetchRequest } from './netProxy'

export interface ExtInstallRequest {
  readonly id: string
  readonly version: string
  /** sha256 hex of the zip bytes, as published by the registry. */
  readonly contentHash: string
  /** The zip bytes (structured-cloned over IPC). */
  readonly bytes: ArrayBuffer
}

export type ExtInstallResult =
  | { readonly ok: true }
  | {
      readonly ok: false
      readonly error: InstallError | 'unauthorized'
      readonly problems?: readonly string[]
    }

export interface ExtOkResult {
  readonly ok: boolean
}

export type ExtDevLoadResult =
  | { readonly ok: true; readonly manifest: ExtensionManifest; readonly devPath: string }
  | { readonly ok: false; readonly problems: readonly string[] }

export interface ExtWindowOpenRequest {
  readonly id: string
  /** The installed semver, or `dev` for a developer registration. */
  readonly version: string
  readonly title: string
  readonly width?: number
  readonly height?: number
}

export type ExtWindowOpenResult =
  | { readonly ok: true; readonly created: boolean }
  | { readonly ok: false }

export interface ExtNetFetchRequest extends NetFetchRequest {
  /** The requesting extension — must be installed; its manifest's
   *  `permissions.network` bounds `allowedOrigins` main-side. */
  readonly id: string
}

export type ExtNetFetchError = NetFetchError | 'unauthorized' | 'not_installed'

export type ExtNetFetchResult =
  | {
      readonly ok: true
      readonly status: number
      readonly headers: Readonly<Record<string, string>>
      readonly bodyBase64: string
    }
  | { readonly ok: false; readonly error: ExtNetFetchError }

export interface ExtensionsBridge {
  index(): Promise<ExtensionIndex>
  install(req: ExtInstallRequest): Promise<ExtInstallResult>
  uninstall(id: string): Promise<ExtOkResult>
  devLoad(path: string): Promise<ExtDevLoadResult>
  devRemove(id: string): Promise<ExtOkResult>
  openWindow(req: ExtWindowOpenRequest): Promise<ExtWindowOpenResult>
  netFetch(req: ExtNetFetchRequest): Promise<ExtNetFetchResult>
}
