import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  notifySourceViewChanged,
  useSourceViewVersion,
  SOURCE_VIEW_STORAGE_KEY
} from './sourceViewEvents'

describe('source view invalidation', () => {
  it('refreshes the same project across mounted consumers and ignores other projects', () => {
    const first = renderHook(() => useSourceViewVersion('p'))
    const second = renderHook(() => useSourceViewVersion('p'))
    const other = renderHook(() => useSourceViewVersion('other'))
    act(() => notifySourceViewChanged('p'))
    expect(first.result.current).toBe(1)
    expect(second.result.current).toBe(1)
    expect(other.result.current).toBe(0)
  })
  it('refreshes on a second desktop window storage event', () => {
    const hook = renderHook(() => useSourceViewVersion('p'))
    act(() =>
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: SOURCE_VIEW_STORAGE_KEY,
          newValue: JSON.stringify({ projectId: 'p' }),
          storageArea: localStorage
        })
      )
    )
    expect(hook.result.current).toBe(1)
  })
})
