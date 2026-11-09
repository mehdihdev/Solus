// SOLUSDEV-323: where the main window's macOS traffic lights sit. The window is
// `hiddenInset`, so the renderer draws the header the lights live in: the
// workspace's 44 px title row, or onboarding's 64 px header. Each screen asks
// for its kind; main moves the lights so they stay centred in that header.
// No electron import: preload reads the channel and type from here too.

export type WindowChrome = 'title' | 'onboarding'

export const WINDOW_CHROME_CHANNEL = 'window:chrome'

/** Top-left of the 12 px lights, so they centre in each header. */
export const TRAFFIC_LIGHTS: Readonly<Record<WindowChrome, { x: number; y: number }>> = {
  title: { x: 16, y: 16 },
  onboarding: { x: 20, y: 26 }
}

export function isWindowChrome(value: unknown): value is WindowChrome {
  return value === 'title' || value === 'onboarding'
}

interface ButtonPositionedWindow {
  setWindowButtonPosition(position: { x: number; y: number } | null): void
}

/** Move the lights for `kind`. macOS only; anything unrecognised is ignored. */
export function applyWindowChrome(
  win: ButtonPositionedWindow | null,
  kind: unknown,
  platform: string
): boolean {
  if (platform !== 'darwin' || !win || !isWindowChrome(kind)) return false
  win.setWindowButtonPosition(TRAFFIC_LIGHTS[kind])
  return true
}
