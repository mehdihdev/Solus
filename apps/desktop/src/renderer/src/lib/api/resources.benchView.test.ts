// SOLUSDEV-319 — typed client for the shared bench view (docs/api/bench-view.md §2–§3).
import { describe, expect, it, vi } from 'vitest'
import { EMPTY_BENCH_VIEW, type BenchView } from '@solus/shared-types'
import { ApiError } from './envelope.types'
import type { ApiClient } from './client'
import { classifyBenchViewError, getBenchView, patchBenchView } from './resources.benchView'

const view: BenchView = { ...EMPTY_BENCH_VIEW, version: 3, updated_at: '2026-10-31T00:00:00Z' }

function stub(result: unknown | (() => never)): {
  client: ApiClient
  calls: { path: string; options?: unknown }[]
} {
  const calls: { path: string; options?: unknown }[] = []
  const client = {
    request: vi.fn(async (path: string, options?: unknown) => {
      calls.push({ path, options })
      if (typeof result === 'function') return (result as () => never)()
      return result as never
    }),
    requestPage: vi.fn()
  } as ApiClient
  return { client, calls }
}

describe('getBenchView', () => {
  it('reads the project view', async () => {
    const { client, calls } = stub(view)
    await expect(getBenchView('p1', client)).resolves.toEqual(view)
    expect(calls[0].path).toBe('/projects/p1/bench/view')
  })

  it('rejects a malformed response instead of rendering it', async () => {
    const { client } = stub({ version: 'seven' })
    await expect(getBenchView('p1', client)).rejects.toThrow(/malformed/i)
  })
})

describe('patchBenchView', () => {
  const ops = [
    {
      kind: 'set_display' as const,
      target: { kind: 'signal' as const, device_id: 'usb:1/3', signal: 'a' },
      patch: { pinned: true }
    }
  ]

  it('sends version, ops and undo=false by default', async () => {
    const result = { version: 4, view: { ...view, version: 4 }, inverse_ops: [] }
    const { client, calls } = stub(result)
    await expect(patchBenchView('p1', { version: 3, ops }, client)).resolves.toEqual(result)
    expect(calls[0]).toEqual({
      path: '/projects/p1/bench/view',
      options: { method: 'PATCH', body: { version: 3, ops, undo: false } }
    })
  })

  it('passes undo=true through for an Undo', async () => {
    const result = { version: 5, view: { ...view, version: 5 }, inverse_ops: ops }
    const { client, calls } = stub(result)
    await patchBenchView('p1', { version: 4, ops, undo: true }, client)
    expect((calls[0].options as { body: { undo: boolean } }).body.undo).toBe(true)
  })

  it('rejects a response with malformed inverse ops', async () => {
    const { client } = stub({ version: 4, view, inverse_ops: [{ kind: 'x' }] })
    await expect(patchBenchView('p1', { version: 3, ops }, client)).rejects.toThrow(/malformed/i)
  })
})

describe('classifyBenchViewError', () => {
  it('surfaces a 409 with current_version', () => {
    const error = new ApiError(409, 'conflict', 'stale', [{ current_version: 9 }])
    expect(classifyBenchViewError(error)).toEqual({ kind: 'conflict', currentVersion: 9 })
  })

  it('tolerates a 409 without usable details', () => {
    const error = new ApiError(409, 'conflict', 'stale', [{ current_version: 'x' }])
    expect(classifyBenchViewError(error)).toEqual({ kind: 'conflict', currentVersion: null })
  })

  it('returns expression_error details, dropping malformed rows', () => {
    const detail = { op_index: 0, code: 'syntax', position: 4, length: 2, message: 'Bad.' }
    const error = new ApiError(422, 'expression_error', 'bad', [detail, { op_index: 'x' }])
    expect(classifyBenchViewError(error)).toEqual({ kind: 'expression', details: [detail] })
  })

  it('maps other API refusals to their code and server sentence', () => {
    const error = new ApiError(422, 'too_many_groups', 'At most 16 plot groups.')
    expect(classifyBenchViewError(error)).toEqual({
      kind: 'refused',
      code: 'too_many_groups',
      message: 'At most 16 plot groups.',
      status: 422
    })
  })

  it('treats a non-API failure as unreachable', () => {
    expect(classifyBenchViewError(new TypeError('fetch failed'))).toEqual({ kind: 'unreachable' })
  })
})
