// Typed access to the Electron preload bridge (window.solus). Returns null when
// the app isn't running under Electron (e.g. the static browser preview), so
// callers can degrade gracefully instead of crashing.
import type { OAuthBridge } from '../features/auth/githubOAuth'

/** Machine-local folder bridge (SOLUSDEV-164): pick a directory, clone a repo,
 *  or reveal a linked folder. Only present under the Electron desktop app. */
export interface FolderBridge {
  pick: () => Promise<string | null>
  reveal: (path: string) => Promise<{ ok: boolean }>
  clone: (input: {
    repoUrl: string
    parentDir: string
  }) => Promise<{ path?: string; error?: string }>
}

interface SolusWindow {
  solus?: { oauth?: OAuthBridge; folder?: FolderBridge }
}

export function getDesktopOAuthBridge(): OAuthBridge | null {
  const w = window as unknown as SolusWindow
  return w.solus?.oauth ?? null
}

export function getDesktopFolderBridge(): FolderBridge | null {
  const w = window as unknown as SolusWindow
  return w.solus?.folder ?? null
}
