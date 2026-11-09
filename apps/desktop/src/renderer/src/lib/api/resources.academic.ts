// Academic plan (SOLUSDEV-319, ADR-042; docs/api/API.md §Academic plan).
// Same injectable-client convention as resources.billing.ts.
import { api, type ApiClient } from './client'

export type AcademicState = 'none' | 'pending' | 'active' | 'expired'

/** GET /billing/academic — the caller's own academic status. */
export interface AcademicStatus {
  state: AcademicState
  /** The verified address (null until verified). */
  email: string | null
  /** The address the live code was sent to (only while a code is usable). */
  pending_email: string | null
  code_expires_at: string | null
  /** When the Academic plan ends (null unless the plan is Academic). */
  expires_at: string | null
  monthly_credits: number
  /** Configured academic domain suffixes, for the hint text. */
  suffixes: string[]
}

export function getAcademicStatus(client: ApiClient = api): Promise<AcademicStatus> {
  return client.request<AcademicStatus>('/billing/academic')
}

export function sendAcademicCode(email: string, client: ApiClient = api): Promise<AcademicStatus> {
  return client.request<AcademicStatus>('/billing/academic/code', {
    method: 'POST',
    body: { email }
  })
}

export function verifyAcademicCode(code: string, client: ApiClient = api): Promise<AcademicStatus> {
  return client.request<AcademicStatus>('/billing/academic/verify', {
    method: 'POST',
    body: { code }
  })
}
