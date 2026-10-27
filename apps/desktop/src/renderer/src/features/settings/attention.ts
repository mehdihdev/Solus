// Settings › Needs attention (SOLUSDEV-318): what the user must act on, derived
// from state Settings already loads. Pure — inputs in, items out, so the order
// and thresholds are tested without rendering.
import type { SolState } from '../../../../main/sol-window/solWindow'
import type { Connection, Subscription } from '../../lib/api/resources'
import { trialState } from './billingFormat'
import type { DriveStatus } from '../../lib/driveBridge'
import { driveBlocked, missingGrants, type DriveGrant } from './driveCopy'

/** A trial this close to its end earns a callout. */
export const TRIAL_WARN_DAYS = 14

export type AttentionItem =
  | { kind: 'capture'; message: string; canOpenSettings: boolean }
  | { kind: 'drive'; missing: readonly DriveGrant[] }
  | { kind: 'trial'; days: number; ended: boolean }
  | { kind: 'reconnect'; connectionId: string; provider: string; login: string | null }

export interface AttentionInput {
  sol: SolState | null
  subscription: Subscription | null
  connections: readonly Connection[]
  /** SOLUSDEV-319: "SOL can use your mouse and keyboard"; absent outside Electron. */
  drive?: DriveStatus | null
  now?: number
}

function captureItem(sol: SolState | null): AttentionItem[] {
  // Off means SOL never captures, so a missing permission is not the user's problem.
  if (!sol?.screenIntelligence || sol.capture.mode === 'available') return []
  return [
    { kind: 'capture', message: sol.capture.message, canOpenSettings: !!sol.capture.settingsUrl }
  ]
}

function driveItem(drive: DriveStatus | null | undefined): AttentionItem[] {
  if (!drive || !driveBlocked(drive)) return []
  return [{ kind: 'drive', missing: missingGrants(drive.trust) }]
}

function trialItem(subscription: Subscription | null, now: number): AttentionItem[] {
  if (!subscription) return []
  const trial = trialState(subscription, now)
  if (trial.kind === 'ended') return [{ kind: 'trial', days: 0, ended: true }]
  if (trial.kind === 'active' && trial.days <= TRIAL_WARN_DAYS) {
    return [{ kind: 'trial', days: trial.days, ended: false }]
  }
  return []
}

function reconnectItems(connections: readonly Connection[]): AttentionItem[] {
  return connections
    .filter((c) => c.status !== 'revoked')
    .filter((c) => c.needs_reauth === 'token_error' || c.health === 'token_expired')
    .map((c) => ({
      kind: 'reconnect' as const,
      connectionId: c.id,
      provider: c.provider,
      login: c.account_login
    }))
}

export function attentionItems(input: AttentionInput): AttentionItem[] {
  const now = input.now ?? Date.now()
  return [
    ...captureItem(input.sol),
    ...driveItem(input.drive),
    ...trialItem(input.subscription, now),
    ...reconnectItems(input.connections)
  ]
}
