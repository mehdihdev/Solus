// SOLX-02: typed access to the preload's sol-window surface (detach the orb to
// the always-on-top window / re-attach it). Same degrade-to-null idiom as
// lib/desktopBridge.ts, kept in-feature: outside Electron (static preview) or
// under an older preload there is simply no detach affordance.
export interface SolWindowBridge {
  detach: () => Promise<{ detached: boolean }>
  attach: () => Promise<{ detached: boolean }>
}

interface SolusWindow {
  solus?: { solWindow?: SolWindowBridge }
}

export function getSolWindowBridge(): SolWindowBridge | null {
  const w = window as unknown as SolusWindow
  return w.solus?.solWindow ?? null
}
