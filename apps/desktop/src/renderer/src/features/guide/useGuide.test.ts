// SOLUS-TU-09 — the Guide data hook.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useGuide } from './useGuide'
import * as guideApi from './guideApi'

vi.mock('./guideApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./guideApi')>()
  return { ...actual, getGuide: vi.fn() }
})

const DETAIL: guideApi.GuideDetail = {
  id: 'g1',
  tool: 'kicad',
  title: 'Wire up your first schematic',
  summary: 'S',
  steps: []
}

beforeEach(() => vi.clearAllMocks())

describe('useGuide', () => {
  it('is idle with no guide selected', () => {
    const { result } = renderHook(() => useGuide(null, '9.0.4'))
    expect(result.current.status).toBe('idle')
    expect(vi.mocked(guideApi.getGuide)).not.toHaveBeenCalled()
  })

  it('loads then resolves to ready', async () => {
    vi.mocked(guideApi.getGuide).mockResolvedValue(DETAIL)
    const { result } = renderHook(() => useGuide('g1', '9.0.4'))
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.guide?.title).toBe(DETAIL.title)
  })

  it('degrades to error when the fetch fails — never a fabricated guide', async () => {
    vi.mocked(guideApi.getGuide).mockRejectedValue(new Error('offline'))
    const { result } = renderHook(() => useGuide('g1', '9.0.4'))
    await waitFor(() => expect(result.current.status).toBe('error'))
    expect(result.current.guide).toBeNull()
  })
})
