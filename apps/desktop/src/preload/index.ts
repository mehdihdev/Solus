import { contextBridge, ipcRenderer } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'
import { createOrbOverlayBridge } from './orbOverlayBridge'
import { createSolBridge } from './solBridge'
import { createDiagnosticsBridge } from './diagnosticsBridge'
import { EXT_CHANNELS } from '../main/extensions/extensions.constants'
import type {
  ExtDevLoadResult,
  ExtInstallRequest,
  ExtInstallResult,
  ExtNetFetchRequest,
  ExtNetFetchResult,
  ExtOkResult,
  ExtWindowOpenRequest,
  ExtWindowOpenResult,
  ExtensionsBridge
} from '../main/extensions/extensions.types'
import type { ExtensionIndex } from '../main/extensions/extensionIndex'
import type { EngineeringPreferences } from '@solus/shared-types'
import type {
  HardwareSourceList,
  HardwareSourcePicked,
  HardwareSourcePickInput,
  HardwareSourceResult
} from '../main/hardwareSources'

export type {
  ExtDevLoadResult,
  ExtInstallRequest,
  ExtInstallResult,
  ExtNetFetchRequest,
  ExtNetFetchResult,
  ExtOkResult,
  ExtWindowOpenRequest,
  ExtWindowOpenResult,
  ExtensionsBridge
}

interface OAuthCallbackResult {
  code?: string
  error?: string
  /** GitHub App install redirect only (SOLUSDEV-216). */
  installationId?: number
  setupAction?: 'install' | 'update' | 'request'
}

/** `install: true` asks main for the longer GitHub App install wait (an org
 *  owner may take minutes). A flag, not a number: main owns the actual timeout. */
interface OAuthAwaitOptions {
  install?: boolean
}

interface CloneResult {
  path?: string
  error?: string
}

// Custom APIs for renderer. `solus.oauth` drives the loopback GitHub flow:
// the renderer gets the redirect URL, builds the authorize URL, then asks the
// main process to open the browser and capture the callback. `solus.bridge`
// relays the Supabase access token to the local companion (SOLUSDEV-154 /
// BRG-04); null means signout. The token is never stored or logged here.
// `solus.folder` links a project to a local directory (pick / clone / reveal)
// — SOLUSDEV-164. `solus.orbOverlay` is the renderer end of the CTR-06
// orb↔overlay push wire (SOLUSDEV-223): validated publish/subscribe over the
// shared channel constants.
const api = {
  hardware: {
    sources: {
      // MAIN verifies the active bridge token/project. No renderer-supplied paths or account IDs.
      list: (): Promise<HardwareSourceResult<HardwareSourceList>> =>
        ipcRenderer.invoke('hardware:sources:list'),
      pick: (
        input: HardwareSourcePickInput = {}
      ): Promise<HardwareSourceResult<HardwareSourcePicked>> =>
        ipcRenderer.invoke('hardware:sources:pick', input),
      recheck: (sourceRef: string): Promise<HardwareSourceResult<HardwareSourcePicked>> =>
        ipcRenderer.invoke('hardware:sources:recheck', { sourceRef })
    }
  },
  oauth: {
    getRedirectUrl: (): Promise<string> => ipcRenderer.invoke('oauth:github:redirect-url'),
    awaitGithub: (authorizeUrl: string): Promise<OAuthCallbackResult> =>
      ipcRenderer.invoke('oauth:github:await', authorizeUrl),
    getConnectorRedirectUrl: (): Promise<string> =>
      ipcRenderer.invoke('oauth:connector:redirect-url'),
    awaitOAuth: (
      authorizeUrl: string,
      expectedState: string,
      options?: OAuthAwaitOptions
    ): Promise<OAuthCallbackResult> =>
      ipcRenderer.invoke('oauth:connector:await', authorizeUrl, expectedState, options),
    // Settle the in-flight connector handshake NOW (wizard closed mid-flow).
    cancelOAuth: (): Promise<boolean> => ipcRenderer.invoke('oauth:connector:cancel')
  },
  bridge: {
    setToken: (token: string | null): Promise<void> => ipcRenderer.invoke('bridge:token', token),
    // The project the companion serves. The bridge WS route is project-scoped,
    // so the companion cannot dial anything until this is set, and it respawns
    // when it changes (the project is fixed in its environment at spawn).
    setProject: (projectId: string | null): Promise<void> =>
      ipcRenderer.invoke('bridge:project', projectId),
    // BYO-license capture (SOLUSDEV-102 / MCP-05): one flat key→value secrets
    // object per server, relayed to the companion's stdin. Never stored or
    // logged anywhere along the way.
    submitLicense: (
      server: string,
      secrets: Record<string, string>
    ): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('bridge:license', server, secrets)
  },
  folder: {
    pick: (): Promise<string | null> => ipcRenderer.invoke('folder:pick'),
    reveal: (path: string): Promise<{ ok: boolean }> => ipcRenderer.invoke('folder:reveal', path),
    openInVscode: (path: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('folder:open-vscode', path),
    clone: (input: { repoUrl: string; parentDir: string }): Promise<CloneResult> =>
      ipcRenderer.invoke('git:clone', input),
    // The ~/.solus project registry (SOLUSDEV-166 / ADR-034): the durable
    // machine-local copy of project→folder links, owned by the main process.
    // The renderer's localStorage store is a display cache over this.
    link: (projectId: string, link: { path: string; repoUrl?: string }): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('folder:link', projectId, link),
    unlink: (projectId: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('folder:unlink', projectId),
    links: (): Promise<Record<string, { path: string; repoUrl?: string; lastOpenedAt?: string }>> =>
      ipcRenderer.invoke('folder:links'),
    // This machine for local-folder sources (SOLUSDEV-249): the companion's
    // instance id + hostname. Null when the id file cannot be read or created.
    machine: (): Promise<{ id: string; name: string } | null> =>
      ipcRenderer.invoke('folder:machine')
  },
  hosted: {
    // Open a hosted MCP add-on's vendor App Store page in the system browser
    // (SOLUSDEV-168). Subscribing cannot be done programmatically, so this is
    // the only way to get the user there.
    openStore: (url: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('hosted:open-store', url)
  },
  billing: {
    // Open a Stripe Checkout / billing-portal URL (from our API) in the browser.
    openExternal: (url: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('billing:open-external', url),
    // Self-contained checkout (SOLUSDEV-114): sandboxed in-app window that
    // closes itself on Stripe's return redirect and reports how it ended.
    openCheckout: (
      url: string
    ): Promise<{ status: 'success' | 'cancel' | 'return' | 'closed' | 'blocked' | 'busy' }> =>
      ipcRenderer.invoke('billing:open-checkout', url)
  },
  solChat: {
    // Machine-local SOL chat cache under ~/.solus (ADR-034 Layer 1 —
    // SOLUSDEV-233). The server stays the source of truth; this makes
    // returning to a chat instant and past chats readable offline.
    read: (projectId: string, conversationId: string): Promise<string | null> =>
      ipcRenderer.invoke('solchat:read', projectId, conversationId),
    write: (projectId: string, conversationId: string, content: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('solchat:write', projectId, conversationId, content),
    remove: (projectId: string, conversationId: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('solchat:remove', projectId, conversationId),
    // Purge every cached chat — the account identity changed (ADR-034).
    clear: (): Promise<{ ok: boolean }> => ipcRenderer.invoke('solchat:clear')
  },
  preferences: {
    // ~/.solus/preferences.json — the user's engineering conventions (ADR-034
    // as amended 2026-09-06, SOLUSDEV-244). Machine-local, user-authored; the
    // main process owns the file and re-validates every write.
    read: (): Promise<{ preferences: EngineeringPreferences; readOnly: boolean } | null> =>
      ipcRenderer.invoke('prefs:read'),
    write: (document: EngineeringPreferences): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('prefs:write', document)
  }
}

// window.api is vestigial (typed `unknown`, still zero renderer consumers) —
// everything the renderer actually calls comes through window.solus, which is
// `api` plus the surfaces below.
// `solus.sol` is the SOL window surface (SOLUSDEV-252 S3): state, mode,
// sees-your-screen, always-on-top, open, and the state/region pushes.
const solus = {
  ...api,
  // SOLUSDEV-235: the renderer draws the title row; on macOS it must inset for the traffic lights.
  platform: process.platform,
  orbOverlay: createOrbOverlayBridge(ipcRenderer),
  sol: createSolBridge(ipcRenderer),
  // SOLUSDEV-311: error reporting to main (validated, scrubbed and logged there).
  diagnostics: createDiagnosticsBridge(ipcRenderer),
  // Extensions (SOLUSDEV-235 / ADR-035, EXT-05): the machine-local bundle cache,
  // developer mode, the window host, and the network egress proxy. The main
  // process re-validates every argument; nothing here holds a credential.
  extensions: {
    index: (): Promise<ExtensionIndex> => ipcRenderer.invoke(EXT_CHANNELS.index),
    install: (req: ExtInstallRequest): Promise<ExtInstallResult> =>
      ipcRenderer.invoke(EXT_CHANNELS.install, req),
    uninstall: (id: string): Promise<ExtOkResult> => ipcRenderer.invoke(EXT_CHANNELS.uninstall, id),
    devLoad: (path: string): Promise<ExtDevLoadResult> =>
      ipcRenderer.invoke(EXT_CHANNELS.devLoad, path),
    devRemove: (id: string): Promise<ExtOkResult> => ipcRenderer.invoke(EXT_CHANNELS.devRemove, id),
    openWindow: (req: ExtWindowOpenRequest): Promise<ExtWindowOpenResult> =>
      ipcRenderer.invoke(EXT_CHANNELS.windowOpen, req),
    netFetch: (req: ExtNetFetchRequest): Promise<ExtNetFetchResult> =>
      ipcRenderer.invoke(EXT_CHANNELS.netFetch, req)
  } satisfies ExtensionsBridge
}

export type SolusBridge = typeof solus

// Use `contextBridge` APIs to expose Electron APIs to
// renderer only if context isolation is enabled, otherwise
// just add to the DOM global.
if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electron', electronAPI)
    contextBridge.exposeInMainWorld('api', api)
    contextBridge.exposeInMainWorld('solus', solus)
  } catch (error) {
    console.error(error)
  }
} else {
  // Fallback when context isolation is off. The global Window augmentation lives
  // in the renderer's type scope, not the preload's, so cast locally here.
  const w = window as unknown as { electron: unknown; api: unknown; solus: unknown }
  w.electron = electronAPI
  w.api = api
  w.solus = solus
}
