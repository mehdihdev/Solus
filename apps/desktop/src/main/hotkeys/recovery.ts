// The hook is loaded once at boot, so two real-world events used to leave
// double-Ctrl dead until a relaunch: Accessibility granted after Solus started
// (the hook was never loaded), and sleep (macOS can disable the event tap).
// This watcher restarts the hotkeys for both, and refreshes the status line so
// a permission granted in System Settings clears its message on its own.

export const HOTKEY_RECOVERY_POLL_MS = 2_000

export interface HotkeyRecoveryDeps {
  platform: string
  /** darwin: `systemPreferences.isTrustedAccessibilityClient(false)` — never prompts. */
  isTrusted(): boolean
  /** The running hotkeys fell back because Accessibility was missing. */
  hookMissingPermission(): boolean
  /** Stop and start the hotkeys (the same path as boot). */
  restart(): void
  /** Re-publish SOL state; the caller publishes only on change. */
  refresh(): void
  /** powerMonitor 'resume' and 'unlock-screen'. */
  onWake(cb: () => void): void
  setInterval(cb: () => void, ms: number): unknown
  clearInterval(handle: unknown): void
}

export function watchHotkeyRecovery(deps: HotkeyRecoveryDeps): { stop(): void } {
  let stopped = false
  deps.onWake(() => {
    if (!stopped) deps.restart()
  })
  const poll =
    deps.platform === 'darwin'
      ? deps.setInterval(() => {
          if (deps.hookMissingPermission() && deps.isTrusted()) deps.restart()
          else deps.refresh()
        }, HOTKEY_RECOVERY_POLL_MS)
      : null
  return {
    stop() {
      stopped = true
      if (poll !== null) deps.clearInterval(poll)
    }
  }
}
