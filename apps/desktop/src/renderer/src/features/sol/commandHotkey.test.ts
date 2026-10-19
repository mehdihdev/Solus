// SOLUSDEV-317: Cmd/Ctrl+Enter approves the newest pending command card in the
// focused SOL surface (sol-page.md "Cmd/Ctrl+Enter approves").
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PendingConfirmation } from '../../lib/api/solStream'
import {
  ARM_DELAY_MS,
  approveShortcut,
  createApprovalRegistry,
  createShortcutGate,
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

describe('registration time', () => {
  it('keeps the first registration time when a card re-registers its approver', () => {
    let now = 1000
    const registry = createApprovalRegistry(() => now)
    const first = registry.register('a', () => true)
    now = 5000
    first()
    registry.register('a', () => false)
    expect(registry.registeredAt('a')).toBe(1000)
    expect(registry.registeredAt('missing')).toBeNull()
  })
})

describe('createShortcutGate (consent race guards)', () => {
  const CTRL_ENTER = { ...key({ ctrlKey: true }), repeat: false }

  function setup(): {
    clock: { now: number }
    registry: ReturnType<typeof createApprovalRegistry>
    gate: ReturnType<typeof createShortcutGate>
    approveA: ReturnType<typeof vi.fn>
    approveB: ReturnType<typeof vi.fn>
  } {
    const clock = { now: 0 }
    const registry = createApprovalRegistry(() => clock.now)
    const gate = createShortcutGate(() => clock.now)
    const approveA = vi.fn(() => true)
    const approveB = vi.fn(() => true)
    registry.register('a', approveA)
    return { clock, registry, gate, approveA, approveB }
  }

  const one = [{ confirmations: [card('a', 'code.exec')] }]
  const two = [{ confirmations: [card('a', 'code.exec'), card('b', 'code.exec')] }]

  it('does nothing before the newest card has been armed for the delay', () => {
    const { clock, registry, gate, approveA } = setup()
    gate.noteNewest(one)
    clock.now = ARM_DELAY_MS - 1
    expect(gate.handle(CTRL_ENTER, registry, one, false)).toEqual({ fired: false, swallow: true })
    expect(approveA).not.toHaveBeenCalled()
    clock.now = ARM_DELAY_MS
    expect(gate.handle(CTRL_ENTER, registry, one, false)).toEqual({ fired: true, swallow: true })
    expect(approveA).toHaveBeenCalledTimes(1)
  })

  it('re-arms when a newer card appears, never approving the newer one early', () => {
    const { clock, registry, gate, approveA, approveB } = setup()
    gate.noteNewest(one)
    clock.now = 5000
    registry.register('b', approveB)
    gate.noteNewest(two)
    clock.now = 5000 + ARM_DELAY_MS - 1
    expect(gate.handle(CTRL_ENTER, registry, two, false).fired).toBe(false)
    expect(approveA).not.toHaveBeenCalled()
    expect(approveB).not.toHaveBeenCalled()
    clock.now = 5000 + ARM_DELAY_MS
    expect(gate.handle(CTRL_ENTER, registry, two, false).fired).toBe(true)
    expect(approveB).toHaveBeenCalledTimes(1)
  })

  it('arms from the keypress itself when the newest card was never noted', () => {
    const { clock, registry, gate, approveA } = setup()
    clock.now = 10_000
    expect(gate.handle(CTRL_ENTER, registry, one, false).fired).toBe(false)
    clock.now = 10_000 + ARM_DELAY_MS
    expect(gate.handle(CTRL_ENTER, registry, one, false).fired).toBe(true)
    expect(approveA).toHaveBeenCalledTimes(1)
  })

  it('arms from registration, not from when the card was first noted', () => {
    const clock = { now: 0 }
    const registry = createApprovalRegistry(() => clock.now)
    const gate = createShortcutGate(() => clock.now)
    gate.noteNewest(one)
    clock.now = 2000
    registry.register('a', () => true)
    clock.now = 2000 + ARM_DELAY_MS - 1
    expect(gate.handle(CTRL_ENTER, registry, one, false).fired).toBe(false)
  })

  it('ignores auto-repeat keydowns', () => {
    const { clock, registry, gate, approveA } = setup()
    gate.noteNewest(one)
    clock.now = 5000
    expect(gate.handle({ ...CTRL_ENTER, repeat: true }, registry, one, false)).toEqual({
      fired: false,
      swallow: true
    })
    expect(approveA).not.toHaveBeenCalled()
  })

  it('needs a keyup before the next shortcut approval', () => {
    const { clock, registry, gate, approveA, approveB } = setup()
    gate.noteNewest(one)
    clock.now = 5000
    expect(gate.handle(CTRL_ENTER, registry, one, false).fired).toBe(true)
    registry.register('b', approveB)
    gate.noteNewest(two)
    clock.now = 50_000
    expect(gate.handle(CTRL_ENTER, registry, two, false).fired).toBe(false)
    expect(approveB).not.toHaveBeenCalled()
    gate.keyUp()
    expect(gate.handle(CTRL_ENTER, registry, two, false).fired).toBe(true)
    expect(approveA).toHaveBeenCalledTimes(1)
    expect(approveB).toHaveBeenCalledTimes(1)
  })

  it('leaves other keys and non-command transcripts alone', () => {
    const { clock, registry, gate } = setup()
    clock.now = 5000
    expect(gate.handle({ ...key({}), repeat: false }, registry, one, false)).toEqual({
      fired: false,
      swallow: false
    })
    expect(
      gate.handle(CTRL_ENTER, registry, [{ confirmations: [card('x', 'kicad.edit')] }], false)
    ).toEqual({ fired: false, swallow: false })
    expect(gate.handle({ ...CTRL_ENTER, isComposing: true }, registry, one, false)).toEqual({
      fired: false,
      swallow: false
    })
  })

  it('swallows the key without approving when the newest card is busy', () => {
    const clock = { now: 0 }
    const registry = createApprovalRegistry(() => clock.now)
    const gate = createShortcutGate(() => clock.now)
    registry.register('a', () => false)
    gate.noteNewest(one)
    clock.now = 5000
    expect(gate.handle(CTRL_ENTER, registry, one, false)).toEqual({ fired: false, swallow: true })
  })
})
