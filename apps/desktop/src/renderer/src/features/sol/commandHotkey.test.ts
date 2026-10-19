// SOLUSDEV-317: Cmd/Ctrl+Enter approves the newest pending command card in the
// focused SOL surface (sol-page.md "Cmd/Ctrl+Enter approves").
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PendingConfirmation } from '../../lib/api/solStream'
import {
  approveShortcut,
  createApprovalRegistry,
  isApproveShortcut,
  newestCommandConfirmation
} from './commandHotkey'

const card = (confirmationId: string, tool: string): PendingConfirmation => ({
  confirmationId,
  tool,
  summary: '',
  preview: []
})

interface Key {
  key: string
  metaKey: boolean
  ctrlKey: boolean
  altKey: boolean
  shiftKey: boolean
  isComposing: boolean
}

const key = (over: Partial<Key>): Key => ({
  key: 'Enter',
  metaKey: false,
  ctrlKey: false,
  altKey: false,
  shiftKey: false,
  isComposing: false,
  ...over
})

afterEach(() => {
  delete (window as unknown as { solus?: unknown }).solus
})

describe('approveShortcut', () => {
  it('uses Ctrl on Linux and in a plain browser', () => {
    expect(approveShortcut()).toEqual({ mac: false, hint: 'Ctrl↵', aria: 'Control+Enter' })
  })

  it('uses Cmd on macOS (from the desktop bridge)', () => {
    ;(window as unknown as { solus: { platform: string } }).solus = { platform: 'darwin' }
    expect(approveShortcut()).toEqual({ mac: true, hint: '⌘↵', aria: 'Meta+Enter' })
  })
})

describe('isApproveShortcut', () => {
  it('matches the platform modifier with Enter only', () => {
    expect(isApproveShortcut(key({ ctrlKey: true }), false)).toBe(true)
    expect(isApproveShortcut(key({ metaKey: true }), true)).toBe(true)
    expect(isApproveShortcut(key({ metaKey: true }), false)).toBe(false)
    expect(isApproveShortcut(key({ ctrlKey: true }), true)).toBe(false)
    expect(isApproveShortcut(key({}), false)).toBe(false)
    expect(isApproveShortcut(key({ ctrlKey: true, shiftKey: true }), false)).toBe(false)
    expect(isApproveShortcut(key({ ctrlKey: true, key: 'a' }), false)).toBe(false)
  })

  it('never fires during IME composition', () => {
    expect(isApproveShortcut(key({ ctrlKey: true, isComposing: true }), false)).toBe(false)
  })
})

describe('newestCommandConfirmation', () => {
  it('picks the last pending command card across messages', () => {
    const items = [
      { confirmations: [card('a', 'code.exec'), card('b', 'onshape.set_variable')] },
      { confirmations: [card('c', 'code.run'), card('d', 'onshape.set_variable')] }
    ]
    expect(newestCommandConfirmation(items)).toBe('c')
  })

  it('is null without a command card', () => {
    expect(newestCommandConfirmation([{ confirmations: [card('b', 'kicad.edit')] }])).toBeNull()
  })
})

describe('createApprovalRegistry', () => {
  it('calls the registered approver and reports whether it fired', () => {
    const registry = createApprovalRegistry()
    const approve = vi.fn(() => true)
    const unregister = registry.register('a', approve)
    expect(registry.approve('a')).toBe(true)
    expect(registry.approve('missing')).toBe(false)
    unregister()
    expect(registry.approve('a')).toBe(false)
  })

  it('does not drop a newer registration when an older one unregisters', () => {
    const registry = createApprovalRegistry()
    const first = registry.register('a', () => false)
    registry.register('a', () => true)
    first()
    expect(registry.approve('a')).toBe(true)
  })
})
