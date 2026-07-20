// A signed-in session must always attempt real API fetches (the persisted
// `linked` onboarding flag only unlocks dev-bypass sessions), and when data is
// still unavailable, a signed-in user is told the API is unreachable — never
// "sign in" (SOLUSDEV-152 live-testing feedback).
import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useOfflineReason, useWorkspaceFetchEnabled } from './workspaceOnline'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'

describe('workspaceOnline', () => {
  beforeEach(() => {
    useAuthStore.setState({ status: 'unauthenticated' })
    useWorkspaceStore.setState({ linked: false })
  })

  it('disables fetches when signed out and unlinked', () => {
    const { result } = renderHook(() => useWorkspaceFetchEnabled())
    expect(result.current).toBe(false)
  })

  it('enables fetches for a linked dev-bypass session', () => {
    useWorkspaceStore.setState({ linked: true })
    const { result } = renderHook(() => useWorkspaceFetchEnabled())
    expect(result.current).toBe(true)
  })

  it('enables fetches for an authenticated session even when the linked flag is stale-false', () => {
    useAuthStore.setState({ status: 'authenticated' })
    const { result } = renderHook(() => useWorkspaceFetchEnabled())
    expect(result.current).toBe(true)
  })

  it('explains offline as signed_out for unauthenticated sessions', () => {
    const { result } = renderHook(() => useOfflineReason())
    expect(result.current).toBe('signed_out')
  })

  it('explains offline as api_unreachable for authenticated sessions', () => {
    useAuthStore.setState({ status: 'authenticated' })
    const { result } = renderHook(() => useOfflineReason())
    expect(result.current).toBe('api_unreachable')
  })
})
