// SOLUSDEV-323: the request each signed-out screen sends main for its window size.
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  rememberedLaunchSize,
  requestWindowSize,
  sizeForPath,
  windowSizeRequest
} from './starterWindow'

describe('windowSizeRequest', () => {
  it('animates and carries the theme ground', () => {
    expect(windowSizeRequest('starter', { reducedMotion: false, background: '#0A0C0F' })).toEqual({
      size: 'starter',
      animate: true,
      background: '#0A0C0F'
    })
  })

  it('jumps under reduced motion and drops a ground that is not #rrggbb', () => {
    expect(windowSizeRequest('full', { reducedMotion: true, background: 'rgb(0,0,0)' })).toEqual({
      size: 'full',
      animate: false
    })
  })
})

describe('sizeForPath', () => {
  it('is the starter at /welcome and the taller auth size on every form', () => {
    expect(sizeForPath('/welcome')).toBe('starter')
    expect(sizeForPath('/login')).toBe('auth')
    expect(sizeForPath('/signup')).toBe('auth')
    expect(sizeForPath('/reset-password')).toBe('auth')
  })
})

describe('requestWindowSize', () => {
  afterEach(() => {
    delete (window as { solus?: unknown }).solus
  })

  it('resolves at once outside Electron', async () => {
    await expect(requestWindowSize('full')).resolves.toBeUndefined()
  })

  it('sends the request through the bridge and waits for main', async () => {
    const setWindowSize = vi.fn().mockResolvedValue(true)
    ;(window as { solus?: unknown }).solus = { setWindowSize }
    await requestWindowSize('auth')
    expect(setWindowSize).toHaveBeenCalledWith(expect.objectContaining({ size: 'auth' }))
  })

  it('never rejects when main fails', async () => {
    ;(window as { solus?: unknown }).solus = {
      setWindowSize: vi.fn().mockRejectedValue(new Error('gone'))
    }
    await expect(requestWindowSize('full')).resolves.toBeUndefined()
  })
})

describe('rememberedLaunchSize', () => {
  afterEach(() => localStorage.clear())

  it('defaults to full', () => {
    expect(rememberedLaunchSize()).toBe('full')
  })

  it('remembers the starter after a signed-out screen, and full after signing in', async () => {
    await requestWindowSize('auth')
    expect(rememberedLaunchSize()).toBe('starter')
    await requestWindowSize('full')
    expect(rememberedLaunchSize()).toBe('full')
  })
})
