// SOLUSDEV-327 — ⌘J (macOS) / Ctrl J (elsewhere) toggles the SOL sidebar. A renderer keydown
// listener like ⌘K, never a global OS hotkey: it fires only while a Solus window has focus.
import { useEffect } from 'react'
import { isMac } from '../commandHotkey'
import { isModKeyShortcut, modKeyHint } from '../../palette/paletteHotkey'

const KEY = 'j'

export function isSidebarShortcut(event: KeyboardEvent, mac: boolean): boolean {
  return isModKeyShortcut(event, mac, KEY)
}

export function sidebarShortcutHint(mac: boolean): string {
  return modKeyHint(mac, KEY)
}

/** `onToggle` should be stable; `enabled` false (the SOL page) leaves the chord alone. */
export function useSidebarHotkey(onToggle: () => void, enabled = true): void {
  useEffect(() => {
    if (!enabled) return
    const mac = isMac()
    const onKey = (event: KeyboardEvent): void => {
      if (!isSidebarShortcut(event, mac)) return
      event.preventDefault()
      onToggle()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onToggle, enabled])
}
