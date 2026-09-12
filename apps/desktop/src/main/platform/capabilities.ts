// SOLUSDEV-252 S3: the ONE place that inspects the platform (docs/architecture/
// sol-window.md §2-§3). Everything platform-touching — hotkeys, key hook,
// capture, tray — reads its static posture from here and reports its live
// status back into the same shape, so the window and the tray show one truth
// and every degrade path has a plain-language message. Pure: no Electron.

export type SessionType = 'x11' | 'wayland' | 'windows' | 'macos' | 'unknown'

export type CapabilityStatus = 'available' | 'needs-permission' | 'unavailable' | 'unknown'

export interface CapabilityState {
  status: CapabilityStatus
  /** Plain language for the window status line and the tray tooltip. */
  message: string
  /** Deep link to the OS pane that grants the permission, when one exists. */
  settingsUrl?: string
}

export interface PlatformBasics {
  platform: NodeJS.Platform
  arch: string
  session: SessionType
}

export interface PlatformCapabilities extends PlatformBasics {
  /** Bare-modifier key up/down (double-tap Ctrl, Ctrl-hold gesture). */
  hook: CapabilityState
  /** `globalShortcut` chords (Ctrl+Space, the fallback chords). */
  globalShortcuts: CapabilityState
  /** `desktopCapturer` region capture. */
  capture: CapabilityState
  /** A tray indicator host. */
  tray: CapabilityState
}

export const MAC_ACCESSIBILITY_URL =
  'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'
export const MAC_SCREEN_RECORDING_URL =
  'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'

export function detectPlatformBasics(
  env: NodeJS.ProcessEnv,
  platform: NodeJS.Platform,
  arch: string
): PlatformBasics {
  const session: SessionType =
    platform === 'win32'
      ? 'windows'
      : platform === 'darwin'
        ? 'macos'
        : platform === 'linux'
          ? env['XDG_SESSION_TYPE'] === 'wayland' || (env['WAYLAND_DISPLAY'] ?? '') !== ''
            ? 'wayland'
            : 'x11'
          : 'unknown'
  return { platform, arch, session }
}

const OK: CapabilityState = { status: 'available', message: '' }

/**
 * What the platform CAN do before anything is probed live. `unknown` means
 * "decided by a self-test at start" (the hook loads or it does not; a
 * permission is granted or it is not) — never assumed.
 */
export function staticCapabilities(basics: PlatformBasics): PlatformCapabilities {
  const { platform, arch, session } = basics
  if (session === 'wayland') {
    return {
      ...basics,
      hook: {
        status: 'unavailable',
        message: 'Hold-Ctrl gestures need X11; on Wayland use Ctrl+Shift+C circle mode.'
      },
      globalShortcuts: {
        status: 'unknown',
        message:
          'Wayland global shortcuts require desktop portal approval; use Open SOL window if unavailable.'
      },
      capture: {
        status: 'unavailable',
        message: 'Screen capture is unavailable on Wayland (the portal would ask on every capture).'
      },
      tray: { status: 'unknown', message: '' }
    }
  }
  const hook: CapabilityState =
    platform === 'linux' && arch === 'arm64'
      ? {
          status: 'unavailable',
          message:
            'The native key hook has no working Linux arm64 build; use Ctrl+Shift+C circle mode and Ctrl+Shift+Space to open SOL.'
        }
      : platform === 'darwin'
        ? {
            status: 'needs-permission',
            message: 'Hold-Ctrl gestures need the Accessibility permission for Solus.',
            settingsUrl: MAC_ACCESSIBILITY_URL
          }
        : { status: 'unknown', message: '' }
  const capture: CapabilityState =
    platform === 'darwin'
      ? {
          status: 'needs-permission',
          message: 'Screen capture needs the Screen Recording permission for Solus.',
          settingsUrl: MAC_SCREEN_RECORDING_URL
        }
      : OK
  return { ...basics, hook, globalShortcuts: OK, capture, tray: { status: 'unknown', message: '' } }
}
