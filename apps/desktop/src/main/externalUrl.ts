// SOLUSDEV-235 (security review H2) — the shared guard for renderer-initiated
// external navigation. `shell.openExternal` is an OS handler launch, not a
// navigation: a `file:`, `vscode:` or `ms-msdt:` URL reaching it runs a
// program. Every BrowserWindow's window-open handler goes through here so an
// anchor in the renderer can only ever reach the system browser over https.
// Pure (no electron import) so the rule is unit-testable; callers inject the opener.

export function isSafeExternalUrl(url: string): boolean {
  try {
    return new URL(url).protocol === 'https:'
  } catch {
    return false
  }
}

type WindowOpenDetails = { url: string }
type WindowOpenResult = { action: 'deny' }

/** Build a `setWindowOpenHandler` callback: https → `open(url)` (errors swallowed), else dropped. */
export function externalOpenHandler(
  open: (url: string) => Promise<void>
): (details: WindowOpenDetails) => WindowOpenResult {
  return ({ url }) => {
    if (isSafeExternalUrl(url)) void open(url).catch(() => undefined)
    return { action: 'deny' }
  }
}
