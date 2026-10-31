// SOLUSDEV-320 P4-T3 — findings client against docs/api/findings.md §3.
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './client'
import {
  acknowledgeFinding,
  dismissFinding,
  getFinding,
  listFindings,
  resolveFinding
} from './findings'

function client(): ApiClient {
  return { request: vi.fn(), requestPage: vi.fn() }
}

describe('findings client', () => {
  it('lists with the documented filters and walks every page', async () => {
    const api = client()
    vi.mocked(api.requestPage)
      .mockResolvedValueOnce({ data: [{ id: 'f1' }], meta: { has_next: true, next_cursor: 'c2' } })
      .mockResolvedValueOnce({ data: [{ id: 'f2' }], meta: { has_next: false } })
    expect(
      await listFindings('p1', { status: 'open', severity: 'critical', subject: 'e1' }, api)
    ).toEqual([{ id: 'f1' }, { id: 'f2' }])
    expect(api.requestPage).toHaveBeenNthCalledWith(
      1,
      '/projects/p1/findings?status=open&severity=critical&subject=e1&limit=500'
    )
    expect(api.requestPage).toHaveBeenNthCalledWith(
      2,
      '/projects/p1/findings?status=open&severity=critical&subject=e1&limit=500&cursor=c2'
    )
  })

  it('refuses a repeated cursor instead of looping', async () => {
    const api = client()
    vi.mocked(api.requestPage).mockResolvedValue({
      data: [],
      meta: { has_next: true, next_cursor: 'same' }
    })
    await expect(listFindings('p1', {}, api)).rejects.toThrow(/cursor/i)
  })

  it('reads one finding from its own route (subjects named)', async () => {
    const api = client()
    vi.mocked(api.request).mockResolvedValue({ id: 'f1', subject_entities: [] })
    expect(await getFinding('p1', 'f1', api)).toEqual({ id: 'f1', subject_entities: [] })
    expect(api.request).toHaveBeenCalledExactlyOnceWith('/projects/p1/findings/f1')
  })

  it('posts resolve, dismiss and acknowledge to the finding routes', async () => {
    const api = client()
    vi.mocked(api.request).mockResolvedValue({ id: 'f1' })
    await resolveFinding('p1', 'f1', { note: 'fixed', fix_ref: 'e9' }, api)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/findings/f1/resolve', {
      method: 'POST',
      body: { note: 'fixed', fix_ref: 'e9' }
    })
    await dismissFinding('p1', 'f1', { cooldown_hours: 24 }, api)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/findings/f1/dismiss', {
      method: 'POST',
      body: { cooldown_hours: 24 }
    })
    await acknowledgeFinding('p1', 'f1', api)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/findings/f1/acknowledge', {
      method: 'POST'
    })
  })
})
