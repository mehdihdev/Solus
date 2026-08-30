// Typed access to the Electron preload bridge (window.solus). Returns null when
// the app isn't running under Electron (e.g. the static browser preview), so
// callers can degrade gracefully instead of crashing.
import type { OAuthBridge } from '../features/auth/githubOAuth'

/** Preload's `solus.bridge` namespace: relays the Supabase access token to the
 *  local companion (SOLUSDEV-154 / BRG-04). Null token means signout. */
export interface CompanionBridge {
  setToken: (token: string | null) => Promise<void>
  /** The project the companion serves. Its bridge URL is project-scoped, so it
   *  stays idle until this is set and respawns when it changes. */
  setProject: (projectId: string | null) => Promise<void>
}

/** Machine-local folder bridge (SOLUSDEV-164): pick a directory, clone a repo,
 *  reveal a linked folder, or open it in VSCode. Only present under the
 *  Electron desktop app.
 *  SOLUSDEV-166 (ADR-034) adds the ~/.solus registry surface: `link`/`unlink`
 *  write the durable machine copy the companion's workspace derives from, and
 *  `links` reads it back for cache hydration. */
export interface FolderBridge {
  pick: () => Promise<string | null>
  reveal: (path: string) => Promise<{ ok: boolean }>
  openInVscode: (path: string) => Promise<{ ok: boolean }>
  clone: (input: {
    repoUrl: string
    parentDir: string
  }) => Promise<{ path?: string; error?: string }>
  link: (projectId: string, link: { path: string; repoUrl?: string }) => Promise<{ ok: boolean }>
  unlink: (projectId: string) => Promise<{ ok: boolean }>
  links: () => Promise<Record<string, { path: string; repoUrl?: string; lastOpenedAt?: string }>>
}

interface SolusWindow {
  solus?: { oauth?: OAuthBridge; bridge?: CompanionBridge; folder?: FolderBridge }
}

export function getDesktopOAuthBridge(): OAuthBridge | null {
  const w = window as unknown as SolusWindow
  return w.solus?.oauth ?? null
}

export function getDesktopCompanionBridge(): CompanionBridge | null {
  const w = window as unknown as SolusWindow
  return w.solus?.bridge ?? null
}

export function getDesktopFolderBridge(): FolderBridge | null {
  const w = window as unknown as SolusWindow
  return w.solus?.folder ?? null
}
