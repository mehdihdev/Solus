// SOLUSDEV-326: SOL's thought summary on a transcript item — pure, immutable helpers.
//
// The text is model output the server masked and bounded (agent/thinking.py); solStream bounds each
// frame again and this module bounds the turn, so a hostile stream cannot grow an item without
// limit. It is rendered as text nodes only (ThinkingBlock), never markdown or HTML.
import type { ChatItem } from './solChatStore'

/** The server's per-turn cap (agent/stream.py THINKING_TURN_CAP). */
export const MAX_THINKING_CHARS = 24_000
/** More stored segments than any real turn has rounds; past it a reloaded value is unproven. */
const MAX_SEGMENTS = 200

/** One stretch of thought, placed after the `afterSteps` tool steps that preceded it. */
export interface ThoughtSegment {
  text: string
  afterSteps: number
}

export interface ThinkingInfo {
  segments: readonly ThoughtSegment[]
  /** Epoch ms of the latest live thought; null for a reloaded turn. */
  lastAt: number | null
  /** How long SOL spent thinking: time inside segments only, not the tool runs between them. */
  ms: number | null
}

const usedChars = (segments: readonly ThoughtSegment[]): number =>
  segments.reduce((total, segment) => total + segment.text.length, 0)

/** `item` with one more piece of live thought, at time `now`. A piece continues the last segment
 *  until a tool step starts; then it opens a new one, placed after that step. */
export function addThought(item: ChatItem, text: string, now: number): ChatItem {
  const prior = item.thinking ?? { segments: [], lastAt: null, ms: 0 }
  const room = MAX_THINKING_CHARS - usedChars(prior.segments)
  const piece = text.slice(0, Math.max(0, room))
  if (!piece) return item
  const steps = item.trace.length
  const last = prior.segments[prior.segments.length - 1]
  const continues = last !== undefined && last.afterSteps === steps
  const segments = continues
    ? [...prior.segments.slice(0, -1), { ...last, text: last.text + piece }]
    : [...prior.segments, { text: piece, afterSteps: steps }]
  const spent = continues && prior.lastAt !== null ? now - prior.lastAt : 0
  return { ...item, thinking: { segments, lastAt: now, ms: (prior.ms ?? 0) + spent } }
}

/** A reloaded turn's `attrs.thinking` (`{segments, ms}`), or null when anything is unproven. */
export function toThinkingInfo(value: unknown): ThinkingInfo | null {
  if (typeof value !== 'object' || value === null) return null
  const { segments, ms } = value as Record<string, unknown>
  const texts = storedSegments(segments)
  const isDuration = typeof ms === 'number' && Number.isFinite(ms) && ms >= 0
  if (texts === null || !isDuration) return null
  return { segments: texts.map((text) => ({ text, afterSteps: 0 })), lastAt: null, ms }
}

/** Stored segments as strings, or null when the list is empty, too long or not all text. */
function storedSegments(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length === 0 || value.length > MAX_SEGMENTS) return null
  if (!value.every((segment): segment is string => typeof segment === 'string')) return null
  return value.reduce((total, text) => total + text.length, 0) > MAX_THINKING_CHARS ? null : value
}

/** A tool id as a few words: `kicad.read_netlist` → `Read netlist`. */
export function humanizeTool(tool: string): string {
  const name = tool.split('.').pop()?.replace(/[_-]+/g, ' ').trim() ?? ''
  return name ? name.charAt(0).toUpperCase() + name.slice(1) : 'Tool'
}

function duration(ms: number): string {
  const seconds = Math.round(ms / 1000)
  if (seconds < 1) return 'a few seconds'
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

/** The folded block's label: "Thought for 12s · 3 steps", or just the steps without a thought. */
export function thoughtSummary(thinking: ThinkingInfo | undefined, steps: number): string {
  const stepText = steps === 0 ? '' : `${steps} ${steps === 1 ? 'step' : 'steps'}`
  if (!thinking) return stepText
  const thought = `Thought for ${duration(thinking.ms ?? 0)}`
  return stepText ? `${thought} · ${stepText}` : thought
}
