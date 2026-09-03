// SOLUSDEV-235 — per-project install state.
import { describe, it, expect, beforeEach } from 'vitest'
import { EXTENSIONS_STORAGE_KEY, selectInstallState, useExtensionsStore } from './extensionsStore'
import { EXTENSION_CATALOG } from './extensions.catalog'

const bundled = EXTENSION_CATALOG.find((m) => m.id === 'experiments')!
const optional = EXTENSION_CATALOG.find((m) => m.id === 'bom')!

beforeEach(() => {
  useExtensionsStore.getState().reset()
  localStorage.clear()
})

describe('extensionsStore', () => {
  it('defaults from the manifest when nothing was touched', () => {
    const { byProject } = useExtensionsStore.getState()
    expect(selectInstallState(byProject, 'p1', bundled).installed).toBe(true)
    expect(selectInstallState(byProject, 'p1', optional).installed).toBe(false)
  })

  it('install / uninstall flip one extension in one project only', () => {
    const s = useExtensionsStore.getState()
    s.install('p1', optional)
    expect(selectInstallState(useExtensionsStore.getState().byProject, 'p1', optional)).toEqual({
      installed: true,
      enabled: true,
      runFrequency: 'every_sync'
    })
    expect(
      selectInstallState(useExtensionsStore.getState().byProject, 'p2', optional).installed
    ).toBe(false)

    s.uninstall('p1', bundled)
    expect(
      selectInstallState(useExtensionsStore.getState().byProject, 'p1', bundled).installed
    ).toBe(false)
    expect(
      selectInstallState(useExtensionsStore.getState().byProject, 'p2', bundled).installed
    ).toBe(true)
  })

  it('reinstalling re-enables a previously disabled extension', () => {
    const s = useExtensionsStore.getState()
    s.setEnabled('p1', optional, false)
    s.install('p1', optional)
    expect(
      selectInstallState(useExtensionsStore.getState().byProject, 'p1', optional).enabled
    ).toBe(true)
  })

  it('setEnabled and setRunFrequency patch without clobbering each other', () => {
    const s = useExtensionsStore.getState()
    s.setEnabled('p1', bundled, false)
    s.setRunFrequency('p1', bundled, 'daily')
    expect(selectInstallState(useExtensionsStore.getState().byProject, 'p1', bundled)).toEqual({
      installed: true,
      enabled: false,
      runFrequency: 'daily'
    })
  })

  it('never mutates the previous state object', () => {
    const before = useExtensionsStore.getState().byProject
    useExtensionsStore.getState().install('p1', optional)
    expect(before).toEqual({})
  })

  it('persists install state but not the selected extension', () => {
    useExtensionsStore.getState().install('p1', optional)
    useExtensionsStore.getState().select('bom')
    const raw = JSON.parse(localStorage.getItem(EXTENSIONS_STORAGE_KEY) ?? '{}')
    expect(raw.state.byProject.p1.bom.installed).toBe(true)
    expect(raw.state.selectedId).toBeUndefined()
  })

  it('reset clears everything', () => {
    useExtensionsStore.getState().install('p1', optional)
    useExtensionsStore.getState().select('bom')
    useExtensionsStore.getState().reset()
    expect(useExtensionsStore.getState()).toMatchObject({ byProject: {}, selectedId: null })
  })
})
