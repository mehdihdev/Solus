// Typed access to the Electron preload bridge (window.solus). Returns null when
// the app isn't running under Electron (e.g. the static browser preview), so
// callers can degrade gracefully instead of crashing.
import type { OAuthBridge } from '../features/auth/githubOAuth'

interface SolusWindow {
  solus?: { oauth?: OAuthBridge }
}

export function getDesktopOAuthBridge(): OAuthBridge | null {
  const w = window as unknown as SolusWindow
  return w.solus?.oauth ?? null
}
