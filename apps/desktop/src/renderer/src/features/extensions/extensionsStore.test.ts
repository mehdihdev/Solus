// SOLUSDEV-235 — the Store's navigation state.
import { describe, it, expect, beforeEach } from 'vitest'
import { useExtensionsStore } from './extensionsStore'

beforeEach(() => {
  useExtensionsStore.getState().reset()
})

describe('extensionsStore', () => {
  it('starts on the catalog', () => {
    expect(useExtensionsStore.getState().selectedId).toBeNull()
  })

  it('selects an extension and returns to the catalog', () => {
    useExtensionsStore.getState().select('bom')
    expect(useExtensionsStore.getState().selectedId).toBe('bom')
    useExtensionsStore.getState().select(null)
    expect(useExtensionsStore.getState().selectedId).toBeNull()
  })

  it('reset clears the selection', () => {
    useExtensionsStore.getState().select('bom')
    useExtensionsStore.getState().reset()
    expect(useExtensionsStore.getState().selectedId).toBeNull()
  })

  it('persists nothing — install state is the server’s, not localStorage’s', () => {
    useExtensionsStore.getState().select('bom')
    expect(localStorage.getItem('solus_extensions_v1')).toBeNull()
  })
})
