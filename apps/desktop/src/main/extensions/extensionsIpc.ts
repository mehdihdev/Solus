// SOLUSDEV-235 / EXT-05 — the IPC seam for `solus.extensions` (the
// solChatCache.ts idiom): every channel's FULL decision — sender gate,
// argument shapes, caps, and the installed-state checks — lives here where it
// is testable against injected fs/net/window surfaces; index.ts only binds
// ipcMain to these with the real sender predicate and real deps.
import { isSafeExtensionId } from '@solus/shared-types'
import type { IpcMainInvokeEvent } from 'electron'
import { installBundle, uninstallExtension } from './bundleInstall'
import { loadDevExtension, removeDevExtension } from './devExtensions'
import type { ExtensionFs } from './extensionFs'
import { readExtensionIndex, type ExtensionIndex, type InstalledExtension } from './extensionIndex'
import { DEV_VERSION, isSafeExtensionVersion } from './extensionPaths'
import { EXT_CHANNELS } from './extensions.constants'
import type {
  ExtDevLoadResult,
  ExtInstallResult,
  ExtNetFetchResult,
  ExtOkResult,
  ExtWindowOpenResult
} from './extensions.types'
import {
  clampWindowSize,
  sanitizeWindowTitle,
  type ExtensionWindowManager
} from './extensionWindow'
import { readInstalledManifest } from './installedManifest'
import { fetchForExtension, type NetProxyDeps } from './netProxy'
import type { OpenZip } from './zipReader'

export interface ExtensionsIpcDeps {
  fs: ExtensionFs
  net: NetProxyDeps
  windows: ExtensionWindowManager
  /** Defaults to the yauzl reader; injectable for tests. */
  openZip?: OpenZip
}

export interface ExtensionsIpc {
  index(senderOk: boolean): ExtensionIndex
  install(senderOk: boolean, payload: unknown): Promise<ExtInstallResult>
  uninstall(senderOk: boolean, id: unknown): ExtOkResult
  devLoad(senderOk: boolean, path: unknown): ExtDevLoadResult
  devRemove(senderOk: boolean, id: unknown): ExtOkResult
  openWindow(senderOk: boolean, payload: unknown): ExtWindowOpenResult
  netFetch(senderOk: boolean, payload: unknown): Promise<ExtNetFetchResult>
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

/** Zip bytes arrive as an ArrayBuffer (or a view) after structured clone. */
function toBytes(value: unknown): Uint8Array | null {
  if (value instanceof ArrayBuffer) return new Uint8Array(value)
  if (ArrayBuffer.isView(value))
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength)
  return null
}

function installArgs(
  payload: unknown
): { id: string; version: string; contentHash: string; bytes: Uint8Array } | null {
  if (!isRecord(payload)) return null
  const { id, version, contentHash } = payload
  const bytes = toBytes(payload.bytes)
  if (
    typeof id !== 'string' ||
    typeof version !== 'string' ||
    typeof contentHash !== 'string' ||
    bytes === null
  )
    return null
  return { id, version, contentHash, bytes }
}

/** The installed entry `version` addresses: the exact semver of a registry
 *  install, or `dev` for a dev registration. */
function installedFor(
  id: unknown,
  version: unknown,
  fs: ExtensionFs
): { id: string; entry: InstalledExtension } | null {
  if (typeof id !== 'string' || !isSafeExtensionId(id) || typeof version !== 'string') return null
  const entry = readExtensionIndex(fs).index.installed[id]
  if (entry === undefined) return null
  const matches =
    version === DEV_VERSION
      ? entry.source === 'dev'
      : isSafeExtensionVersion(version) && entry.source === 'registry' && entry.version === version
  return matches ? { id, entry } : null
}

function openWindow(payload: unknown, deps: ExtensionsIpcDeps): ExtWindowOpenResult {
  if (!isRecord(payload)) return { ok: false }
  const installed = installedFor(payload.id, payload.version, deps.fs)
  if (installed === null) return { ok: false }
  return deps.windows.open({
    id: installed.id,
    version: payload.version as string,
    title: sanitizeWindowTitle(payload.title),
    ...clampWindowSize(payload)
  })
}

async function netFetch(payload: unknown, deps: ExtensionsIpcDeps): Promise<ExtNetFetchResult> {
  if (!isRecord(payload) || typeof payload.id !== 'string' || !isSafeExtensionId(payload.id))
    return { ok: false, error: 'invalid_input' }
  if (!Array.isArray(payload.allowedOrigins)) return { ok: false, error: 'invalid_input' }
  // The renderer host passes what it believes the manifest allows; main
  // bounds that by the manifest it can read from disk (§7: never trust the
  // caller's copy of a permission).
  const manifest = readInstalledManifest(payload.id, deps.fs)
  if (manifest === null) return { ok: false, error: 'not_installed' }
  const declared = new Set<string>(manifest.permissions.network)
  const allowedOrigins = payload.allowedOrigins.filter(
    (o): o is string => typeof o === 'string' && declared.has(o)
  )
  return fetchForExtension(
    {
      url: payload.url as string,
      ...(payload.method !== undefined ? { method: payload.method as string } : {}),
      ...(payload.headers !== undefined
        ? { headers: payload.headers as Record<string, string> }
        : {}),
      ...(payload.bodyBase64 !== undefined ? { bodyBase64: payload.bodyBase64 as string } : {}),
      allowedOrigins
    },
    deps.net
  )
}

export function createExtensionsIpc(deps: ExtensionsIpcDeps): ExtensionsIpc {
  const { fs } = deps
  return {
    index: (senderOk) =>
      senderOk ? readExtensionIndex(fs).index : { schema_version: 1, installed: {} },
    async install(senderOk, payload) {
      if (!senderOk) return { ok: false, error: 'unauthorized' }
      const args = installArgs(payload)
      if (args === null) return { ok: false, error: 'invalid_input' }
      return installBundle(args, fs, deps.openZip)
    },
    uninstall: (senderOk, id) =>
      senderOk && typeof id === 'string' ? uninstallExtension(id, fs) : { ok: false },
    devLoad: (senderOk, path) =>
      senderOk ? loadDevExtension(path, fs) : { ok: false, problems: ['unauthorized sender'] },
    devRemove: (senderOk, id) =>
      senderOk && typeof id === 'string' ? removeDevExtension(id, fs) : { ok: false },
    openWindow: (senderOk, payload) => (senderOk ? openWindow(payload, deps) : { ok: false }),
    netFetch: (senderOk, payload) =>
      senderOk ? netFetch(payload, deps) : Promise.resolve({ ok: false, error: 'unauthorized' })
  }
}

/** Structural slice of ipcMain for invoke registration. */
export interface ExtensionsIpcMain {
  handle(
    channel: string,
    listener: (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown
  ): void
}

/** Bind the seven channels; `isAllowedSender` is required, never defaulted. */
export function registerExtensionsIpc(
  ipc: ExtensionsIpcMain,
  isAllowedSender: (event: IpcMainInvokeEvent) => boolean,
  impl: ExtensionsIpc
): void {
  ipc.handle(EXT_CHANNELS.index, (event) => impl.index(isAllowedSender(event)))
  ipc.handle(EXT_CHANNELS.install, (event, payload) =>
    impl.install(isAllowedSender(event), payload)
  )
  ipc.handle(EXT_CHANNELS.uninstall, (event, id) => impl.uninstall(isAllowedSender(event), id))
  ipc.handle(EXT_CHANNELS.devLoad, (event, path) => impl.devLoad(isAllowedSender(event), path))
  ipc.handle(EXT_CHANNELS.devRemove, (event, id) => impl.devRemove(isAllowedSender(event), id))
  ipc.handle(EXT_CHANNELS.windowOpen, (event, payload) =>
    impl.openWindow(isAllowedSender(event), payload)
  )
  ipc.handle(EXT_CHANNELS.netFetch, (event, payload) =>
    impl.netFetch(isAllowedSender(event), payload)
  )
}
