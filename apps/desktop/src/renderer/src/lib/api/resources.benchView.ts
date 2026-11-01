// SOLUSDEV-319 — typed wrappers for the team-shared bench view (docs/api/bench-view.md §2–§3).
// Responses are validated before use: names, units and expressions are team-authored data.
import {
  isBenchView,
  isBenchViewOp,
  type BenchView,
  type BenchViewExpressionErrorDetail,
  type BenchViewPatchBody,
  type BenchViewPatchResult
} from '@solus/shared-types'
import { api, type ApiClient } from './client'
import { ApiError } from './envelope.types'

const viewPath = (projectId: string): string => `/projects/${projectId}/bench/view`

export async function getBenchView(projectId: string, client: ApiClient = api): Promise<BenchView> {
  const data = await client.request<unknown>(viewPath(projectId))
  if (!isBenchView(data)) throw new Error('Malformed bench view response')
  return data
}

function isPatchResult(value: unknown): value is BenchViewPatchResult {
  if (typeof value !== 'object' || value === null) return false
  const row = value as Record<string, unknown>
  return (
    Number.isInteger(row.version) &&
    isBenchView(row.view) &&
    Array.isArray(row.inverse_ops) &&
    row.inverse_ops.length <= 64 &&
    row.inverse_ops.every(isBenchViewOp)
  )
}

export async function patchBenchView(
  projectId: string,
  body: BenchViewPatchBody,
  client: ApiClient = api
): Promise<BenchViewPatchResult> {
  const data = await client.request<unknown>(viewPath(projectId), {
    method: 'PATCH',
    body: { version: body.version, ops: body.ops, undo: body.undo ?? false }
  })
  if (!isPatchResult(data)) throw new Error('Malformed bench view write response')
  return data
}

export type BenchViewFailure =
  | { kind: 'conflict'; currentVersion: number | null }
  | { kind: 'expression'; details: BenchViewExpressionErrorDetail[] }
  | { kind: 'refused'; code: string; message: string; status: number }
  | { kind: 'unreachable' }

function isExpressionDetail(value: unknown): value is BenchViewExpressionErrorDetail {
  if (typeof value !== 'object' || value === null) return false
  const row = value as Record<string, unknown>
  return (
    Number.isInteger(row.op_index) &&
    typeof row.code === 'string' &&
    Number.isInteger(row.position) &&
    Number.isInteger(row.length) &&
    typeof row.message === 'string'
  )
}

function conflictVersion(details: readonly unknown[] | undefined): number | null {
  const first = details?.[0]
  if (typeof first !== 'object' || first === null) return null
  const version = (first as Record<string, unknown>).current_version
  return Number.isInteger(version) ? (version as number) : null
}

/** Narrow a failed GET/PATCH into the cases the bench view UI handles (§3.3). */
export function classifyBenchViewError(error: unknown): BenchViewFailure {
  if (!(error instanceof ApiError)) return { kind: 'unreachable' }
  if (error.status === 409)
    return { kind: 'conflict', currentVersion: conflictVersion(error.details) }
  if (error.code === 'expression_error')
    return { kind: 'expression', details: (error.details ?? []).filter(isExpressionDetail) }
  return { kind: 'refused', code: error.code, message: error.message, status: error.status }
}
