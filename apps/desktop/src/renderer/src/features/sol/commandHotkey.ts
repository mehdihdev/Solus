// SOLUSDEV-317: Cmd+Enter (macOS) / Ctrl+Enter (elsewhere) approves the NEWEST
// pending command card in the focused SOL surface (sol-page.md, sol-window.md).
// Scoped to the surface's own keydown — never a global shortcut, so main's
// global hotkeys are untouched. It is an approval gesture on a visible card,
// exactly like clicking Approve: the card's own decide path runs, and a busy
// or spent card refuses it.
import { createContext, useContext, useEffect, useState } from 'react'
import { getDesktopPlatform } from '../../lib/desktopBridge'
import { isCommandTool } from './commandCard'

export interface ApproveShortcut {
  readonly mac: boolean
  /** Shown on the Approve button. */
  readonly hint: string
  /** `aria-keyshortcuts` value. */
  readonly aria: string
}

function isMac(): boolean {
  const platform = getDesktopPlatform()
  if (platform !== null) return platform === 'darwin'
  return typeof navigator !== 'undefined' && /mac/i.test(navigator.platform)
}

export function approveShortcut(): ApproveShortcut {
  return isMac()
    ? { mac: true, hint: '⌘↵', aria: 'Meta+Enter' }
    : { mac: false, hint: 'Ctrl↵', aria: 'Control+Enter' }
}

interface KeyLike {
  readonly key: string
  readonly metaKey: boolean
  readonly ctrlKey: boolean
  readonly altKey: boolean
  readonly shiftKey: boolean
  readonly isComposing?: boolean
}

export function isApproveShortcut(event: KeyLike, mac: boolean): boolean {
  if (event.key !== 'Enter' || event.isComposing === true) return false
  if (event.altKey || event.shiftKey) return false
  return mac ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey
}

interface ConfirmationHolder {
  readonly confirmations: readonly { readonly confirmationId: string; readonly tool: string }[]
}

/** The newest pending command card in transcript order; null when none. */
export function newestCommandConfirmation(items: readonly ConfirmationHolder[]): string | null {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const cards = items[i].confirmations
    for (let j = cards.length - 1; j >= 0; j -= 1) {
      if (isCommandTool(cards[j].tool)) return cards[j].confirmationId
    }
  }
  return null
}

/** Security review (consent race): a card's preview must have been in view
 *  AND the card the newest command card for this long before the shortcut can
 *  approve it, so a card that appears (e.g. from an auto-resume) under a key
 *  press already on its way — or one never scrolled into view — is never
 *  approved by it. */
export const ARM_DELAY_MS = 700

/** Each mounted command card registers how to approve itself; the approver
 *  returns false when the card is busy or spent. Separately, the card reports
 *  when its verbatim preview is in view: that is when the arming clock starts
 *  (sol-page.md "Command preview is open"). Leaving view before the clock has
 *  run resets it; a card already armed stays armed. */
export interface ApprovalRegistry {
  register: (confirmationId: string, approve: () => boolean) => () => void
  approve: (confirmationId: string) => boolean
  setInView: (confirmationId: string, inView: boolean) => void
  forgetView: (confirmationId: string) => void
  inViewSince: (confirmationId: string) => number | null
}

export function createApprovalRegistry(now: () => number = () => Date.now()): ApprovalRegistry {
  const approvers = new Map<string, () => boolean>()
  const inViewSince = new Map<string, number>()
  return {
    register(confirmationId, approve) {
      approvers.set(confirmationId, approve)
      return () => {
        if (approvers.get(confirmationId) === approve) approvers.delete(confirmationId)
      }
    },
    approve: (confirmationId) => approvers.get(confirmationId)?.() ?? false,
    setInView(confirmationId, inView) {
      const since = inViewSince.get(confirmationId)
      if (inView) {
        if (since === undefined) inViewSince.set(confirmationId, now())
        return
      }
      if (since !== undefined && now() - since < ARM_DELAY_MS) inViewSince.delete(confirmationId)
    },
    forgetView: (confirmationId) => {
      inViewSince.delete(confirmationId)
    },
    inViewSince: (confirmationId) => inViewSince.get(confirmationId) ?? null
  }
}

export const CommandApprovalContext = createContext<ApprovalRegistry | null>(null)

/** Register a command card's approver with the surrounding SOL surface. */
export function useRegisterCommandApproval(
  confirmationId: string,
  approve: (() => boolean) | null
): void {
  const registry = useContext(CommandApprovalContext)
  useEffect(() => {
    if (!registry || !approve) return
    return registry.register(confirmationId, approve)
  }, [registry, confirmationId, approve])
}

interface ShortcutKey extends KeyLike {
  readonly repeat: boolean
  /** The press came from the composer while it holds text (sol-page.md
   *  "Composer drafts win"): consumed, never an approval. */
  readonly composerDraft?: boolean
}

export interface ShortcutResult {
  /** A card was approved. */
  readonly fired: boolean
  /** Keep the key from the composer: the shortcut targeted a command card. */
  readonly swallow: boolean
}

export interface ShortcutGate {
  /** Record which command card is newest now (called as the transcript changes). */
  noteNewest: (items: readonly ConfirmationHolder[]) => void
  /** Any keyup: the next shortcut approval may fire. */
  keyUp: () => void
  handle: (
    event: ShortcutKey,
    registry: ApprovalRegistry,
    items: readonly ConfirmationHolder[],
    mac: boolean
  ) => ShortcutResult
}

const PASS: ShortcutResult = { fired: false, swallow: false }
const BLOCKED: ShortcutResult = { fired: false, swallow: true }

export function createShortcutGate(now: () => number = () => Date.now()): ShortcutGate {
  let newestId: string | null = null
  let newestSince = 0
  let awaitingKeyUp = false

  const note = (id: string | null): void => {
    if (id === newestId) return
    newestId = id
    newestSince = now()
  }

  return {
    noteNewest: (items) => note(newestCommandConfirmation(items)),
    keyUp: () => {
      awaitingKeyUp = false
    },
    handle(event, registry, items, mac) {
      if (!isApproveShortcut(event, mac)) return PASS
      const newest = newestCommandConfirmation(items)
      if (newest === null) return PASS
      note(newest)
      if (event.composerDraft === true || event.repeat || awaitingKeyUp) return BLOCKED
      const inView = registry.inViewSince(newest)
      if (inView === null) return BLOCKED
      if (now() - Math.max(newestSince, inView) < ARM_DELAY_MS) return BLOCKED
      if (!registry.approve(newest)) return BLOCKED
      awaitingKeyUp = true
      return { fired: true, swallow: true }
    }
  }
}

/** Marks the SOL composer input; a press there while it holds text is a
 *  draft, never an approval. */
export const COMPOSER_ATTR = 'data-sol-composer'

function isComposerDraft(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLInputElement && target.hasAttribute(COMPOSER_ATTR) && target.value !== ''
  )
}

/** The surface's capture-phase keydown. Works from anywhere in the surface,
 *  including an empty composer; swallows the key whenever it targeted a command
 *  card, so a blocked shortcut never falls through to sending the draft. */
export function approveOnShortcut(
  event: React.KeyboardEvent,
  gate: ShortcutGate,
  registry: ApprovalRegistry,
  items: readonly ConfirmationHolder[]
): void {
  const native = event.nativeEvent as KeyboardEvent
  const composing = native.isComposing || native.keyCode === 229
  const result = gate.handle(
    {
      key: event.key,
      metaKey: event.metaKey,
      ctrlKey: event.ctrlKey,
      altKey: event.altKey,
      shiftKey: event.shiftKey,
      isComposing: composing,
      repeat: event.repeat,
      composerDraft: isComposerDraft(event.target)
    },
    registry,
    items,
    approveShortcut().mac
  )
  if (!result.swallow) return
  event.preventDefault()
  event.stopPropagation()
}

/** Wire the gate to a SOL surface: note the newest card as the transcript
 *  changes, and re-allow the shortcut on any keyup (inside the surface or not)
 *  or when the window loses focus. */
export function useCommandShortcut(items: readonly ConfirmationHolder[]): {
  registry: ApprovalRegistry
  onKeyDownCapture: (event: React.KeyboardEvent) => void
} {
  const [registry] = useState(() => createApprovalRegistry())
  const [gate] = useState(() => createShortcutGate())
  useEffect(() => gate.noteNewest(items), [gate, items])
  useEffect(() => {
    const release = (): void => gate.keyUp()
    window.addEventListener('keyup', release, true)
    window.addEventListener('blur', release)
    return () => {
      window.removeEventListener('keyup', release, true)
      window.removeEventListener('blur', release)
    }
  }, [gate])
  return {
    registry,
    onKeyDownCapture: (event) => approveOnShortcut(event, gate, registry, items)
  }
}
