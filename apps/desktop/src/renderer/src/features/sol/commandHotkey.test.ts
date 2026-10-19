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

describe('preview in view (arming clock)', () => {
  it('starts the clock when the preview comes into view, not at registration', () => {
    let now = 1000
    const registry = createApprovalRegistry(() => now)
    registry.register('a', () => true)
    expect(registry.inViewSince('a')).toBeNull()
    now = 4000
    registry.setInView('a', true)
    now = 9000
    registry.setInView('a', true)
    expect(registry.inViewSince('a')).toBe(4000)
    expect(registry.inViewSince('missing')).toBeNull()
  })

  it('resets the clock when the preview leaves view before arming', () => {
    let now = 0
    const registry = createApprovalRegistry(() => now)
    registry.setInView('a', true)
    now = ARM_DELAY_MS - 1
    registry.setInView('a', false)
    expect(registry.inViewSince('a')).toBeNull()
    now = 5000
    registry.setInView('a', true)
    expect(registry.inViewSince('a')).toBe(5000)
  })

  it('keeps an armed card armed when its preview later leaves view', () => {
    let now = 0
    const registry = createApprovalRegistry(() => now)
    registry.setInView('a', true)
    now = ARM_DELAY_MS
    registry.setInView('a', false)
    expect(registry.inViewSince('a')).toBe(0)
  })

  it('forgets the clock when the card unmounts', () => {
    const registry = createApprovalRegistry(() => 5000)
    registry.setInView('a', true)
    registry.forgetView('a')
    expect(registry.inViewSince('a')).toBeNull()
  })
})

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
  registry.setInView('a', true)
  return { clock, registry, gate, approveA, approveB }
}

const one = [{ confirmations: [card('a', 'code.exec')] }]
const two = [{ confirmations: [card('a', 'code.exec'), card('b', 'code.exec')] }]

describe('createShortcutGate (consent race guards)', () => {
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
    registry.setInView('b', true)
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

  it('arms from when the preview came into view, not from when the card was noted', () => {
    const clock = { now: 0 }
    const registry = createApprovalRegistry(() => clock.now)
    const gate = createShortcutGate(() => clock.now)
    registry.register('a', () => true)
    gate.noteNewest(one)
    clock.now = 2000
    registry.setInView('a', true)
    clock.now = 2000 + ARM_DELAY_MS - 1
    expect(gate.handle(CTRL_ENTER, registry, one, false).fired).toBe(false)
    clock.now = 2000 + ARM_DELAY_MS
    expect(gate.handle(CTRL_ENTER, registry, one, false).fired).toBe(true)
  })
})

describe('createShortcutGate (preview visibility and composer drafts)', () => {
  it('never approves a card whose preview has not been in view', () => {
    const clock = { now: 0 }
    const registry = createApprovalRegistry(() => clock.now)
    const gate = createShortcutGate(() => clock.now)
    const approve = vi.fn(() => true)
    registry.register('a', approve)
    gate.noteNewest(one)
    clock.now = 60_000
    expect(gate.handle(CTRL_ENTER, registry, one, false)).toEqual({ fired: false, swallow: true })
    expect(approve).not.toHaveBeenCalled()
  })

  it('consumes the key without approving while the composer holds a draft', () => {
    const { clock, registry, gate, approveA } = setup()
    gate.noteNewest(one)
    clock.now = 5000
    expect(gate.handle({ ...CTRL_ENTER, composerDraft: true }, registry, one, false)).toEqual({
      fired: false,
      swallow: true
    })
    expect(approveA).not.toHaveBeenCalled()
    expect(gate.handle({ ...CTRL_ENTER, composerDraft: false }, registry, one, false).fired).toBe(
      true
    )
  })

  it('leaves a drafted Ctrl+Enter alone when no command card is pending', () => {
    const { registry, gate } = setup()
    const none = [{ confirmations: [card('x', 'kicad.edit')] }]
    expect(gate.handle({ ...CTRL_ENTER, composerDraft: true }, registry, none, false)).toEqual({
      fired: false,
      swallow: false
    })
  })
})

describe('createShortcutGate (key handling)', () => {
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
    registry.setInView('b', true)
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
    registry.setInView('a', true)
    gate.noteNewest(one)
    clock.now = 5000
    expect(gate.handle(CTRL_ENTER, registry, one, false)).toEqual({ fired: false, swallow: true })
  })
})
