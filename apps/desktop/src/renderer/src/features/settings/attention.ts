// Settings › Needs attention (SOLUSDEV-318): what the user must act on, derived
// from state Settings already loads. Pure — inputs in, items out, so the order
// and thresholds are tested without rendering.
import type { SolState } from '../../../../main/sol-window/solWindow'
import type { Connection, Subscription } from '../../lib/api/resources'
import { trialState } from './billingFormat'

/** A trial this close to its end earns a callout. */
export const TRIAL_WARN_DAYS = 14

export type AttentionItem =
  | { kind: 'capture'; message: string; canOpenSettings: boolean }
  | { kind: 'trial'; days: number; ended: boolean }
  | { kind: 'reconnect'; connectionId: string; provider: string; login: string | null }

export interface AttentionInput {
  sol: SolState | null
  subscription: Subscription | null
  connections: readonly Connection[]
  now?: number
}

function captureItem(sol: SolState | null): AttentionItem[] {
  // Off means SOL never captures, so a missing permission is not the user's problem.
  if (!sol?.screenIntelligence || sol.capture.mode === 'available') return []
  return [
    { kind: 'capture', message: sol.capture.message, canOpenSettings: !!sol.capture.settingsUrl }
  ]
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
    ...trialItem(input.subscription, now),
    ...reconnectItems(input.connections)
  ]
}
