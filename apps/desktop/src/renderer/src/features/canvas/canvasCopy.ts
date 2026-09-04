// SOLUSDEV-235 / EXT-15 — the canvas's honest notes (pure; shared with tests).
import type { SaveState } from './useWidgetLayout'

export const OFFLINE_NOTE = 'Offline — layout kept on this machine until reconnected'

export const SAVE_TEXT: Readonly<Record<SaveState, string>> = {
  saved: 'Saved',
  saving: 'Saving…',
  offline: OFFLINE_NOTE
}

/** Count-aware: "1 widget … isn't available and was removed." */
export function prunedNote(count: number): string {
  const one = count === 1
  return `${count} widget${one ? '' : 's'} from your saved layout ${one ? "isn't" : "aren't"} available and ${one ? 'was' : 'were'} removed.`
}
