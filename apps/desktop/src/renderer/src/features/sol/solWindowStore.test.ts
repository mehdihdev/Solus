// SOLUSDEV-252 S3: the renderer mirror of the main process's SOL state
// (sol:state pushes) and the one in-memory circled region (sol:region).
// Runtime-only — nothing here persists; pixels never leave this process.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useAuthStore } from '../../store/authStore'
import {
  SOL_REGION,
  SOL_STATE,
  fakeSolBridge,
  installSolBridge,
  uninstallSolBridge
} from './solWindow.fixtures'
import {
  connectSolBridge,
  disconnectSolBridge,
  regionToScreenshot,
  useSolActionMode,
  useSolWindowStore
} from './solWindowStore'

beforeEach(() => {
  disconnectSolBridge()
  useSolWindowStore.setState({ state: null, region: null })
})
afterEach(() => {
  disconnectSolBridge()
  uninstallSolBridge()
})

describe('connectSolBridge', () => {
  it('asks main for the state once (this is what flushes a queued region) and mirrors pushes', async () => {
    const bridge = fakeSolBridge()
    await act(async () => connectSolBridge(bridge))
    expect(bridge.getState).toHaveBeenCalledTimes(1)
    expect(useSolWindowStore.getState().state).toEqual(SOL_STATE)
    act(() => bridge.pushState({ ...SOL_STATE, actionMode: 'do' }))
    expect(useSolWindowStore.getState().state?.actionMode).toBe('do')
    act(() => bridge.pushRegion(SOL_REGION))
    expect(useSolWindowStore.getState().region).toBe(SOL_REGION)
  })

  it('is idempotent per renderer and does nothing without a bridge', async () => {
    const bridge = fakeSolBridge()
    await act(async () => {
      connectSolBridge(bridge)
      connectSolBridge(bridge)
    })
    expect(bridge.onState).toHaveBeenCalledTimes(1)
    disconnectSolBridge()
    expect(() => connectSolBridge(null)).not.toThrow()
    expect(useSolWindowStore.getState().state).toEqual(SOL_STATE) // untouched
  })

  it('clearRegion drops the pixels from memory', () => {
    useSolWindowStore.getState().setRegion(SOL_REGION)
    useSolWindowStore.getState().clearRegion()
    expect(useSolWindowStore.getState().region).toBeNull()
  })
})

// FIX-2-R H1: the region is another account's pixels the moment the account
// changes — sign-out or an in-place identity swap both drop it.
describe('account teardown drops the region', () => {
  afterEach(() => useAuthStore.setState({ status: 'unauthenticated', user: null }))

  it('sign-out clears the region', () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' } })
    useSolWindowStore.getState().setRegion(SOL_REGION)
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    expect(useSolWindowStore.getState().region).toBeNull()
  })

  it('an identity swap clears the region; a same-account refresh keeps it', () => {
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' } })
    useSolWindowStore.getState().setRegion(SOL_REGION)
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' } })
    expect(useSolWindowStore.getState().region).toBe(SOL_REGION)
    useAuthStore.setState({ status: 'authenticated', user: { email: 'c@d.dev' } })
    expect(useSolWindowStore.getState().region).toBeNull()
  })
})

describe('regionToScreenshot', () => {
  it('shapes the MessageCreate.screenshot body — crop as data, full screen as context', () => {
    expect(regionToScreenshot(SOL_REGION)).toEqual({
      media_type: 'image/png',
      data: SOL_REGION.pngBase64,
      width: 320,
      height: 200,
      source: { app: 'Onshape', title: 'Bracket v3' },
      context: SOL_REGION.contextPngBase64
    })
  })

  // FIX-2-R M3: a long window title must not 422 the turn (and lose the capture).
  it('truncates the source to the API caps (app 128, title 256) and passes null through', () => {
    const long = { ...SOL_REGION, source: { app: 'a'.repeat(200), title: 't'.repeat(300) } }
    const shot = regionToScreenshot(long)
    expect(shot.source?.app).toHaveLength(128)
    expect(shot.source?.title).toHaveLength(256)
    expect(regionToScreenshot({ ...SOL_REGION, source: null }).source).toBeNull()
  })
})

describe('useSolActionMode', () => {
  it('outside Electron keeps a local mode with the composer default (Do)', () => {
    const { result } = renderHook(() => useSolActionMode())
    expect(result.current.mode).toBe('do')
    act(() => result.current.setMode('guide'))
    expect(result.current.mode).toBe('guide')
  })

  it('inside Electron reads the shared mode and toggles through the bridge', async () => {
    const bridge = fakeSolBridge()
    installSolBridge(bridge)
    const { result } = renderHook(() => useSolActionMode())
    await act(async () => undefined)
    expect(result.current.mode).toBe('guide')
    act(() => result.current.setMode('do'))
    expect(bridge.setMode).toHaveBeenCalledWith('do')
    // The mode flips when main confirms via the state push, not optimistically.
    expect(result.current.mode).toBe('guide')
    act(() => bridge.pushState({ ...SOL_STATE, actionMode: 'do' }))
    expect(result.current.mode).toBe('do')
  })
})
