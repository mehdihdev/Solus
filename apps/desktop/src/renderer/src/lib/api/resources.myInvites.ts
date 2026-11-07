// SOLUSDEV-319: typed client for "Invitations to me" (docs/api/API-implementation.md §4) —
// the pending email invites addressed to the signed-in person across every team, shown in
// Home's team rail. The server never sends the invite token or email here.
import { api, type ApiClient } from './client'
import { ApiError } from './envelope.types'
import type { AcceptInviteResult, TeamRole } from './resources'

export interface MyInvite {
  id: string
  team: { id: string; name: string }
  role: TeamRole
  /** Null when the inviter's account is gone. */
  invited_by: { name: string } | null
  created_at: string
  expires_at: string
}

/** How the rail words a failed list, accept or decline. */
export type MyInviteRefusal = 'unverified' | 'at_limit' | 'gone' | 'already_member' | 'failed'

const path = (id: string): string => `/users/me/invites/${encodeURIComponent(id)}`

export function listMyInvites(client: ApiClient = api): Promise<MyInvite[]> {
  return client.request<MyInvite[]>('/users/me/invites')
}

export function acceptMyInvite(id: string, client: ApiClient = api): Promise<AcceptInviteResult> {
  return client.request<AcceptInviteResult>(`${path(id)}/accept`, { method: 'POST' })
}

export async function declineMyInvite(id: string, client: ApiClient = api): Promise<void> {
  await client.request<null>(`${path(id)}/decline`, { method: 'POST' })
}

/** The invite closed before the click (revoked, declined, used, expired, or not mine). */
const GONE_CODES: ReadonlySet<string> = new Set([
  'invite_revoked',
  'invite_declined',
  'invite_already_accepted',
  'invite_expired',
  'not_found'
])

export function myInviteRefusal(error: unknown): MyInviteRefusal {
  if (!(error instanceof ApiError)) return 'failed'
  if (error.code === 'email_not_verified') return 'unverified'
  if (error.code === 'plan_limit_reached') return 'at_limit'
  if (error.code === 'already_member') return 'already_member'
  if (GONE_CODES.has(error.code)) return 'gone'
  return 'failed'
}
