// SOLUSDEV-323: each signed-out screen names the window size it wants; main
// animates the main window to it (natively on macOS). The theme's ground goes
// along so the growing edge is painted, and reduced motion makes it a jump.
import {
  setDesktopWindowSize,
  type DesktopWindowSize,
  type DesktopWindowSizeRequest
} from '../../lib/desktopBridge'

const HEX_COLOUR = /^#[0-9a-f]{6}$/i

interface MotionEnv {
  reducedMotion: boolean
  background: string
}

export function windowSizeRequest(
  size: DesktopWindowSize,
  env: MotionEnv
): DesktopWindowSizeRequest {
  const background = env.background.trim()
  return {
    size,
    animate: !env.reducedMotion,
    ...(HEX_COLOUR.test(background) ? { background } : {})
  }
}

/** The starter is short; every form (sign in, create account, reset) shares one taller size. */
export function sizeForPath(pathname: string): Exclude<DesktopWindowSize, 'full'> {
  return pathname === '/welcome' ? 'starter' : 'auth'
}

function currentMotionEnv(): MotionEnv {
  return {
    reducedMotion: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
    background: getComputedStyle(document.documentElement).getPropertyValue('--bg')
  }
}

const LAUNCH_SIZE_KEY = 'solus.window.launchSize'

/**
 * The size the window last settled on (`starter` signed out, `full` signed in),
 * so the splash can ask for it while the session loads and a signed-out launch
 * never shows full-size first. Defaults to full.
 */
export function rememberedLaunchSize(): 'starter' | 'full' {
  try {
    return localStorage.getItem(LAUNCH_SIZE_KEY) === 'starter' ? 'starter' : 'full'
  } catch {
    return 'full'
  }
}

function rememberLaunchSize(size: DesktopWindowSize): void {
  try {
    localStorage.setItem(LAUNCH_SIZE_KEY, size === 'full' ? 'full' : 'starter')
  } catch {
    // Storage blocked: the splash falls back to full, as before.
  }
}

/** Resize the window; never rejects (a failed resize must not block signing in). */
export async function requestWindowSize(size: DesktopWindowSize): Promise<void> {
  rememberLaunchSize(size)
  try {
    await setDesktopWindowSize(windowSizeRequest(size, currentMotionEnv()))
  } catch {
    // Main is gone or refused: the page still works at whatever size it has.
  }
}
