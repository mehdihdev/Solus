// Who may invoke a privileged IPC channel (SOLUSDEV-102 / SOLUSDEV-96).
//
// Its own module because `index.ts` bootstraps Electron at import — it takes the
// single-instance lock and builds a BrowserWindow — so nothing there can be
// unit-tested. The gate gets a test instead of a comment.

/** True when an IPC invoke came from `window`'s own renderer, and not some other
 *  webContents that gained IPC reach.
 *
 *  Fails CLOSED on a null window: before one exists (or after teardown) there is
 *  no legitimate sender, so a handler refuses rather than allows. */
export function isFromWindow(sender: unknown, window: { webContents: unknown } | null): boolean {
  return window !== null && sender === window.webContents
}
