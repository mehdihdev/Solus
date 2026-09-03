// SOLUSDEV-235 / EXT-13 — "Open in window ↗" (wireflow §3): IPC
// `ext:window:open` with the manifest's window view. Main sanitizes and clamps
// the title/size again; one window per extension, a second call focuses it.
import { getDesktopExtensionsBridge } from '../../../lib/desktopBridge'
import type { InstalledBundleState } from '../frame/installedBundle'

export async function openExtensionWindow(state: InstalledBundleState): Promise<boolean> {
  if (state.status !== 'ready' || !state.manifest.views.window) return false
  const bridge = getDesktopExtensionsBridge()
  if (bridge === null) return false
  const view = state.manifest.views.window
  const title = state.policy.mode === 'dev' ? `${view.title} — DEV` : view.title
  const result = await bridge.openWindow({
    id: state.policy.extensionId,
    version: state.version,
    title,
    width: view.width,
    height: view.height
  })
  return result.ok
}
