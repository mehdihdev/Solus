import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useCredits } from './useCredits'
import * as resources from '../../lib/api/resources'

beforeEach(() => vi.restoreAllMocks())

describe('useCredits', () => {
  it('does not fetch while disabled (offline Settings)', () => {
    const spy = vi.spyOn(resources, 'getCredits')
    const { result } = renderHook(() => useCredits(false))
    expect(spy).not.toHaveBeenCalled()
    expect(result.current).toEqual({ balance: null, unlimited: false })
  })

  it('reads the balance once enabled', async () => {
    vi.spyOn(resources, 'getCredits').mockResolvedValue({ user_id: 'u1', balance: 1840 })
    const { result } = renderHook(() => useCredits(true))
    await waitFor(() => expect(result.current).toEqual({ balance: 1840, unlimited: false }))
  })

  it('reports unlimited plans as unlimited', async () => {
    vi.spyOn(resources, 'getCredits').mockResolvedValue({
      user_id: 'u1',
      balance: 0,
      unlimited: true
    })
    const { result } = renderHook(() => useCredits(true))
    await waitFor(() => expect(result.current.unlimited).toBe(true))
  })

  it('leaves the balance unknown when the read fails, never a fake zero', async () => {
    const spy = vi.spyOn(resources, 'getCredits').mockRejectedValue(new Error('503'))
    const { result } = renderHook(() => useCredits(true))
    await waitFor(() => expect(spy).toHaveBeenCalled())
    expect(result.current).toEqual({ balance: null, unlimited: false })
  })
})
