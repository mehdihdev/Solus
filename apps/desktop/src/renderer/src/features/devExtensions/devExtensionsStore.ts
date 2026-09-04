// SOLUSDEV-235 / EXT-20 — developer-mode registrations as the renderer holds
// them (ADR-035 §4, extensions-runtime.md §7). Main owns the durable copy
// (~/.solus/extensions/index.json, `source: 'dev'` + `devPath`) and is the only
// validator; this store mirrors what main last said so the Settings → Developer
// surface can list rows with current problems and the frame resolver can mount
// `dev:<id>` with `mode: 'dev'`. Deliberately NOT persisted: on boot `hydrate()`
// re-reads the index and re-validates every folder, so a manifest edited while
// Solus was closed is never served from a stale renderer snapshot.
//
// Grants: a dev session is the developer's own local code, so every scope and
// origin the manifest declares is granted for the session (§7) — but only
// once the developer has ACKNOWLEDGED that fact for this (slug, devPath)
// (SEC-H3): until `acknowledge(slug)` the registration is listed in Settings
// and mounts nowhere (`selectDevRegistration` is null). The acknowledgement
// is session-held like the grants themselves; a different folder for the
// same slug, or a restart, asks again. Nothing here is ever sent to the
// server, and the host still refuses server-attributed methods in dev mode.
import { create, type StoreApi, type UseBoundStore } from 'zustand'
import type { ExtensionManifest } from '@solus/shared-types'
import { getDesktopExtensionsBridge, type ExtensionsBridge } from '../../lib/desktopBridge'
import type { DevRegistration } from '../extensions/frame/installedBundle'

export interface DevExtensionEntry {
  /** Main's validated manifest — null when the folder has never validated this
   *  session (the row is listed as "not loaded" so it can be fixed or removed). */
  readonly manifest: ExtensionManifest | null
  /** The registered folder, as main canonicalised it. */
  readonly devPath: string
  readonly loadedAt: string
  /** The contract's dotted-path problems from the LAST validation, verbatim. */
  readonly problems: readonly string[]
  /** SEC-H3: the developer accepted "runs with every permission it declares". */
  readonly acknowledged: boolean
}

export type DevLoadOutcome =
  | { readonly ok: true; readonly slug: string }
  | {
      readonly ok: false
      /** The registration the failure was attributed to, or null for a fresh folder. */
      readonly slug: string | null
      readonly problems: readonly string[]
    }

export interface DevExtensionsState {
  readonly entries: Readonly<Record<string, DevExtensionEntry>>
  /** Re-read main's index and re-validate every dev folder. */
  hydrate(): Promise<void>
  load(path: string): Promise<DevLoadOutcome>
  reload(slug: string): Promise<DevLoadOutcome>
  remove(slug: string): Promise<boolean>
  /** SEC-H3: accept the declared permissions for this (slug, devPath). */
  acknowledge(slug: string): void
  reset(): void
}

export interface DevExtensionsDeps {
  bridge(): ExtensionsBridge | null
  now(): string
}

export const NO_DESKTOP_PROBLEM = 'Extensions run in the Solus desktop app.'
export const BRIDGE_FAILURE_PROBLEM = 'Solus could not reach the desktop bridge.'
export const NOT_LOADED_PROBLEM = 'That extension is not loaded.'

type DevLoadResult = Awaited<ReturnType<ExtensionsBridge['devLoad']>>
type Entries = Readonly<Record<string, DevExtensionEntry>>

/** IPC can reject (bridge torn down mid-call); a rejection reads as a problem. */
async function devLoad(bridge: ExtensionsBridge, path: string): Promise<DevLoadResult> {
  try {
    return await bridge.devLoad(path)
  } catch {
    return { ok: false, problems: [BRIDGE_FAILURE_PROBLEM] }
  }
}

function loadedEntry(
  result: Extract<DevLoadResult, { ok: true }>,
  now: string,
  previous: DevExtensionEntry | undefined
): DevExtensionEntry {
  // The acknowledgement is per (slug, devPath): a reload of the same folder
  // keeps it, a different folder under the same id asks again.
  const acknowledged =
    previous !== undefined && previous.devPath === result.devPath && previous.acknowledged
  return {
    manifest: result.manifest,
    devPath: result.devPath,
    loadedAt: now,
    problems: [],
    acknowledged
  }
}

/** The failure row: the last good manifest (if any) with the fresh problems. */
function failedEntry(
  previous: DevExtensionEntry | undefined,
  devPath: string,
  problems: readonly string[],
  now: string
): DevExtensionEntry {
  return {
    manifest: previous?.manifest ?? null,
    devPath,
    loadedAt: previous?.loadedAt ?? now,
    problems,
    acknowledged: previous?.acknowledged ?? false
  }
}

function slugOfPath(entries: Entries, path: string): string | null {
  const hit = Object.entries(entries).find(([, entry]) => entry.devPath === path)
  return hit === undefined ? null : hit[0]
}

async function hydrateEntries(bridge: ExtensionsBridge, now: string): Promise<Entries> {
  const index = await bridge.index()
  const devRows = Object.entries(index.installed).flatMap(([slug, row]) =>
    row.source === 'dev' && typeof row.devPath === 'string' ? [[slug, row.devPath] as const] : []
  )
  const validated = await Promise.all(
    devRows.map(async ([slug, devPath]): Promise<readonly [string, DevExtensionEntry]> => {
      const result = await devLoad(bridge, devPath)
      return result.ok
        ? [result.manifest.extension.id, loadedEntry(result, now, undefined)]
        : [slug, failedEntry(undefined, devPath, result.problems, now)]
    })
  )
  return Object.fromEntries(validated)
}

function without(entries: Entries, slug: string): Entries {
  return Object.fromEntries(Object.entries(entries).filter(([key]) => key !== slug))
}

/** Build a store over injectable deps; `useDevExtensionsStore` is the app's. */
export function createDevExtensionsStore(
  deps: DevExtensionsDeps
): UseBoundStore<StoreApi<DevExtensionsState>> {
  return create<DevExtensionsState>()((set, get) => ({
    entries: {},

    async hydrate() {
      const bridge = deps.bridge()
      if (bridge === null) return
      const entries = await hydrateEntries(bridge, deps.now())
      set({ entries })
    },

    async load(path) {
      const bridge = deps.bridge()
      if (bridge === null) return { ok: false, slug: null, problems: [NO_DESKTOP_PROBLEM] }
      const result = await devLoad(bridge, path)
      if (result.ok) {
        const slug = result.manifest.extension.id
        set((s) => ({
          entries: { ...s.entries, [slug]: loadedEntry(result, deps.now(), s.entries[slug]) }
        }))
        return { ok: true, slug }
      }
      const slug = slugOfPath(get().entries, path)
      if (slug !== null) {
        set((s) => ({
          entries: {
            ...s.entries,
            [slug]: failedEntry(s.entries[slug], path, result.problems, deps.now())
          }
        }))
      }
      return { ok: false, slug, problems: result.problems }
    },

    async reload(slug) {
      const entry = get().entries[slug]
      if (entry === undefined) return { ok: false, slug: null, problems: [NOT_LOADED_PROBLEM] }
      return get().load(entry.devPath)
    },

    async remove(slug) {
      const bridge = deps.bridge()
      if (bridge === null) return false
      const result = await bridge.devRemove(slug)
      if (!result.ok) return false
      set((s) => ({ entries: without(s.entries, slug) }))
      return true
    },

    acknowledge(slug) {
      set((s) => {
        const entry = s.entries[slug]
        if (entry === undefined || entry.acknowledged) return s
        return { entries: { ...s.entries, [slug]: { ...entry, acknowledged: true } } }
      })
    },

    reset: () => set({ entries: {} })
  }))
}

/** The session's developer registration for `slug` in the shape the frame
 *  resolver consumes (installedBundle.ts `DevRegistration`), or null — also
 *  null until the developer acknowledged the declared permissions (SEC-H3). */
export function selectDevRegistration(
  state: Pick<DevExtensionsState, 'entries'>,
  slug: string
): DevRegistration | null {
  const entry = state.entries[slug]
  const manifest = entry?.acknowledged ? entry.manifest : null
  if (manifest === null) return null
  return {
    manifest,
    grantedScopes: [...manifest.permissions.scopes],
    grantedNetwork: [...manifest.permissions.network]
  }
}

export const useDevExtensionsStore = createDevExtensionsStore({
  bridge: getDesktopExtensionsBridge,
  now: () => new Date().toISOString()
})
