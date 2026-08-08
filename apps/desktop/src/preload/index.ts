import { contextBridge, ipcRenderer } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'

interface OAuthCallbackResult {
  code?: string
  error?: string
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
// — SOLUSDEV-164.
const api = {
  oauth: {
    getRedirectUrl: (): Promise<string> => ipcRenderer.invoke('oauth:github:redirect-url'),
    awaitGithub: (authorizeUrl: string): Promise<OAuthCallbackResult> =>
      ipcRenderer.invoke('oauth:github:await', authorizeUrl)
  },
  bridge: {
    setToken: (token: string | null): Promise<void> => ipcRenderer.invoke('bridge:token', token),
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
      ipcRenderer.invoke('git:clone', input)
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
  }
}

export type SolusBridge = typeof api

// Use `contextBridge` APIs to expose Electron APIs to
// renderer only if context isolation is enabled, otherwise
// just add to the DOM global.
if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electron', electronAPI)
    contextBridge.exposeInMainWorld('api', api)
    contextBridge.exposeInMainWorld('solus', api)
  } catch (error) {
    console.error(error)
  }
} else {
  // Fallback when context isolation is off. The global Window augmentation lives
  // in the renderer's type scope, not the preload's, so cast locally here.
  const w = window as unknown as { electron: unknown; api: unknown; solus: unknown }
  w.electron = electronAPI
  w.api = api
  w.solus = api
}
