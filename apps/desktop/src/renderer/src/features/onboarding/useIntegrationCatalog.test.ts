// The hook renders the curated fallback synchronously and upgrades to the live
// backend catalog when the load resolves (SOLUSDEV-100).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import * as catalogModule from './integrationCatalog'
import { FALLBACK_CATALOG } from './integrationCatalog'
import { useIntegrationCatalog } from './useIntegrationCatalog'

vi.mock('./integrationCatalog', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./integrationCatalog')>()
  return { ...actual, loadIntegrationCatalog: vi.fn() }
})

const mockedLoad = vi.mocked(catalogModule.loadIntegrationCatalog)

describe('useIntegrationCatalog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('serves the fallback immediately, then the live catalog', async () => {
    const live = [...FALLBACK_CATALOG, { ...FALLBACK_CATALOG[1], id: 'altium', name: 'Altium' }]
    mockedLoad.mockResolvedValue(live)

    const { result } = renderHook(() => useIntegrationCatalog())
    expect(result.current).toEqual(FALLBACK_CATALOG)

    await waitFor(() => expect(result.current).toEqual(live))
  })

  it('keeps the fallback when the load never upgrades it', async () => {
    mockedLoad.mockResolvedValue(FALLBACK_CATALOG)
    const { result } = renderHook(() => useIntegrationCatalog())
    await waitFor(() => expect(mockedLoad).toHaveBeenCalled())
    expect(result.current).toEqual(FALLBACK_CATALOG)
  })
})
