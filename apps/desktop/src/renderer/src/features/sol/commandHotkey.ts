// SOLUSDEV-317: Cmd+Enter (macOS) / Ctrl+Enter (elsewhere) approves the NEWEST
// pending command card in the focused SOL surface (sol-page.md, sol-window.md).
// Scoped to the surface's own keydown — never a global shortcut, so main's
// global hotkeys are untouched. It is an approval gesture on a visible card,
// exactly like clicking Approve: the card's own decide path runs, and a busy
// or spent card refuses it.
import { createContext, useContext, useEffect } from 'react'
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

/** Each mounted command card registers how to approve itself; the approver
 *  returns false when the card is busy or spent. */
export interface ApprovalRegistry {
  register: (confirmationId: string, approve: () => boolean) => () => void
  approve: (confirmationId: string) => boolean
}

export function createApprovalRegistry(): ApprovalRegistry {
  const approvers = new Map<string, () => boolean>()
  return {
    register(confirmationId, approve) {
      approvers.set(confirmationId, approve)
      return () => {
        if (approvers.get(confirmationId) === approve) approvers.delete(confirmationId)
      }
    },
    approve: (confirmationId) => approvers.get(confirmationId)?.() ?? false
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

/** The surface's capture-phase keydown: approve the newest command card and,
 *  only when that fired, keep the key from submitting the composer. */
export function approveOnShortcut(
  event: React.KeyboardEvent,
  registry: ApprovalRegistry,
  items: readonly ConfirmationHolder[]
): void {
  const native = event.nativeEvent as KeyboardEvent
  const composing = native.isComposing || native.keyCode === 229
  if (composing || !isApproveShortcut(event, approveShortcut().mac)) return
  const newest = newestCommandConfirmation(items)
  if (newest === null || !registry.approve(newest)) return
  event.preventDefault()
  event.stopPropagation()
}
