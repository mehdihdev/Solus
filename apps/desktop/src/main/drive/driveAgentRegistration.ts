// SOLUSDEV-319 drive slice 3b (docs/architecture/sol-drive.md §2.1, §5;
// ADR-041 amendment 3b): the packaged app registers the solus-input launch
// agent through SMAppService (Electron's agentService login item) only while
// drive is wanted, and unregisters it otherwise. launchd then starts the
// helper as its own responsible process, so the grants attach to
// SolusInput.app. Electron enters through the injected `LoginItemsApi`.
import type { DriveAgentState } from './driveStatus'
import { DRIVE_AGENT_PLIST } from './driveHelper'

export const DRIVE_AGENT_SERVICE = {
  type: 'agentService',
  serviceName: DRIVE_AGENT_PLIST
} as const

/** Where macOS asks the user to approve a registered agent (`requires_approval`). */
export const DRIVE_LOGIN_ITEMS_URL =
  'x-apple.systempreferences:com.apple.LoginItems-Settings.extension'

/** The slice of Electron `app` this needs. */
export interface LoginItemsApi {
  setLoginItemSettings(settings: { openAtLogin: boolean; type: string; serviceName: string }): void
  getLoginItemSettings(options: { type: string; serviceName: string }): { status?: unknown }
}

const STATUS: Readonly<Record<string, DriveAgentState>> = {
  enabled: 'enabled',
  'requires-approval': 'requires_approval',
  'not-registered': 'not_registered',
  'not-found': 'not_found'
}

/** Electron's `LoginItemSettings.status` → DriveAgentState; null when unknown. */
export function mapAgentStatus(status: unknown): DriveAgentState | null {
  return typeof status === 'string' && Object.hasOwn(STATUS, status) ? STATUS[status] : null
}

export interface AgentRegistration {
  /** Register (true) or unregister (false); a repeated decision is a no-op. */
  apply(wanted: boolean): void
  state(): DriveAgentState | null
}

export function createAgentRegistration(
  api: LoginItemsApi,
  warn: (message: string) => void = () => undefined
): AgentRegistration {
  let applied: boolean | null = null
  return {
    apply(wanted) {
      if (applied === wanted) return
      try {
        api.setLoginItemSettings({ openAtLogin: wanted, ...DRIVE_AGENT_SERVICE })
        applied = wanted
      } catch (error) {
        applied = null // retried on the next apply
        warn(`[drive] agent ${wanted ? 'registration' : 'unregistration'} failed: ${String(error)}`)
      }
    },
    state() {
      try {
        return mapAgentStatus(api.getLoginItemSettings(DRIVE_AGENT_SERVICE).status)
      } catch {
        return null
      }
    }
  }
}
