// SOLUSDEV-327 — Solus-authored per-screen copy for the SOL sidebar (sol-sidebar.md §6).
// The only non-constant input is the focused entity's display name, which is graph content:
// it is collapsed to one line and capped, and rendered as text only.

export interface SidebarCopy {
  /** Mono header tag naming SOL's scope. */
  tag: string
  /** SOL's first line on an empty conversation. */
  greeting: string
  /** Starting questions; a chip sends its text. */
  suggestions: readonly string[]
  placeholder: string
}

export const MAX_TAG_NAME = 32

interface ScreenCopy {
  label: string
  greeting: string
  suggestions: readonly string[]
  placeholder: string
}

const GENERIC_GREETING = 'Ask SOL about this project.'
const GENERIC_PLACEHOLDER = 'Ask SOL anything'

const LABELS: Readonly<Record<string, string>> = {
  home: 'HOME',
  workspace: 'WORKSPACE',
  bench: 'LIVE BENCH',
  hardware: 'HARDWARE',
  store: 'STORE',
  billing: 'BILLING',
  settings: 'SETTINGS',
  alert: 'ALERT',
  'ext-page': 'EXTENSION'
}

const SCREENS: Readonly<Record<string, Omit<ScreenCopy, 'label'>>> = {
  workspace: {
    greeting: 'I can see the workspace graph. Ask about any node, or how two connect.',
    suggestions: ["What does this project's graph cover?", 'Is anything wired inconsistently?'],
    placeholder: 'Ask about the workspace'
  },
  bench: {
    greeting: "I'm watching the bench with you. Ask about a signal or what to test.",
    suggestions: ['What should I test first?', 'What can I put on the bench?'],
    placeholder: 'Ask about the bench'
  },
  hardware: {
    greeting:
      'SOL sees what is plugged into this computer. Plug something in, or tell it what you have.',
    suggestions: ['What is plugged in?', "What does the workspace describe that isn't here?"],
    placeholder: 'Ask SOL, or tell it what you have'
  },
  home: {
    greeting: 'Ask about this project, or what changed since you were last here.',
    suggestions: ['What changed recently?', 'What should I work on next?'],
    placeholder: GENERIC_PLACEHOLDER
  }
}

function screenCopy(screen: string): ScreenCopy {
  const label = LABELS[screen] ?? screen.toUpperCase()
  const own = SCREENS[screen]
  return own
    ? { label, ...own }
    : { label, greeting: GENERIC_GREETING, suggestions: [], placeholder: GENERIC_PLACEHOLDER }
}

/** Bidi overrides/isolates and zero-width marks: removed, so a part name cannot visually
 *  reorder or hide text in the tag. */
const INVISIBLE = /[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g
// eslint-disable-next-line no-control-regex
const SPACING = /[\s\u0000-\u001f\u007f]+/g

/** One line, capped — never markup, never multi-line ingested text in the header. */
function tagName(name: string | null): string | null {
  const flat = (name ?? '').replace(INVISIBLE, '').replace(SPACING, ' ').trim()
  if (!flat) return null
  // Code points, not UTF-16 units: the cap never splits a surrogate pair.
  const points = Array.from(flat)
  return points.length > MAX_TAG_NAME ? `${points.slice(0, MAX_TAG_NAME - 1).join('')}…` : flat
}

export function sidebarCopy(screen: string, focusedName: string | null): SidebarCopy {
  const copy = screenCopy(screen)
  const name = screen === 'workspace' ? tagName(focusedName) : null
  return {
    tag: name ? `${copy.label} · ${name}` : copy.label,
    greeting: copy.greeting,
    suggestions: copy.suggestions,
    placeholder: copy.placeholder
  }
}
