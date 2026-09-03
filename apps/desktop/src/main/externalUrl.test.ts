// SOLUSDEV-235 (security review H2) — the one window-open handler every
// BrowserWindow shares: https reaches the OS browser, nothing else does.
import { describe, it, expect, vi } from 'vitest'
import { externalOpenHandler, isSafeExternalUrl } from './externalUrl'

describe('isSafeExternalUrl', () => {
  it('accepts only well-formed https URLs', () => {
    expect(isSafeExternalUrl('https://docs.solusforge.com/extensions')).toBe(true)
    for (const bad of [
      'http://docs.solusforge.com',
      'file:///etc/passwd',
      'javascript:alert(1)',
      'vscode://file/x',
      'smb://share/x',
      'ms-msdt:/id',
      'not a url',
      ''
    ])
      expect(isSafeExternalUrl(bad)).toBe(false)
  })
})

describe('externalOpenHandler', () => {
  it('opens https externally and always denies the in-app window', () => {
    const open = vi.fn().mockResolvedValue(undefined)
    const handler = externalOpenHandler(open)
    expect(handler({ url: 'https://ok.example/x' })).toEqual({ action: 'deny' })
    expect(open).toHaveBeenCalledWith('https://ok.example/x')
  })

  it('never hands a non-https URL to the OS', () => {
    const open = vi.fn().mockResolvedValue(undefined)
    const handler = externalOpenHandler(open)
    expect(handler({ url: 'file:///Users/x/.solus/credentials' })).toEqual({ action: 'deny' })
    expect(handler({ url: 'javascript:alert(1)' })).toEqual({ action: 'deny' })
    expect(open).not.toHaveBeenCalled()
  })

  it('swallows an opener failure instead of crashing main', async () => {
    const open = vi.fn().mockRejectedValue(new Error('no handler'))
    const handler = externalOpenHandler(open)
    expect(() => handler({ url: 'https://ok.example' })).not.toThrow()
    await Promise.resolve()
  })
})
