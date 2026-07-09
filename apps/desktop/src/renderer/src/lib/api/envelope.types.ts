// REST response envelopes, per API.md §1.4.
// Success: { data, meta?, links? }   Error: { error: { code, message, details? } }

// Route/schema types generated from the backend's OpenAPI (`pnpm gen:api`,
// regenerated on build). Re-exported here so the typed client can reference
// backend-derived shapes without hand-maintaining them. The envelope wrappers
// below stay hand-written; per-route `data` shapes come from `components`.
export type { paths, components, operations } from './schema'

export interface ApiMeta {
  has_next?: boolean
  next_cursor?: string | null
  total?: number
}

export interface ApiSuccess<T> {
  data: T
  meta?: ApiMeta
  links?: Record<string, string>
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details?: unknown[]
  }
}

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly details?: unknown[]

  constructor(status: number, code: string, message: string, details?: unknown[]) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}
