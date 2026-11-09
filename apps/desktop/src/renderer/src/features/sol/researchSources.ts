// SOLUSDEV-321 P1-T5: the web sources of a turn's research, as the desktop keeps them. ONE
// validator reads both the live `research_sources` frame and the `attrs.research_sources` the
// server stored on the assistant turn (solChatItems.turnToSourcedItem), so a reload shows what
// streaming showed.
//
// Everything in it is untrusted web text (CLAUDE.md §7): bounded, shape-checked, and a payload
// with anything unproven in it is dropped whole — never half delivered. It imports nothing at
// runtime (solChatItems and solStream both import IT), so no cycle can form through it.
import type { Patch } from './solChatItems'

/** The server sends at most this many sources, titles of at most this many characters, URLs of
 *  at most `MAX_SOURCE_URL`, and a query of at most `MAX_QUESTION` (agent/research.py; the title
 *  and query caps are `RESEARCH_TITLE_CAP` and `RESEARCH_QUESTION_CAP` in agent/stream.py). */
export const MAX_RESEARCH_SOURCES = 20
export const MAX_SOURCE_TITLE = 160
export const MAX_SOURCE_URL = 2048
const MAX_QUESTION = 400

/** Whether `text` has more than `cap` code points — how the server counts (`max_length`). An
 *  astral character is two UTF-16 units but one code point, so comparing `.length` would drop a
 *  payload the server allows. Up to `cap` units it cannot be over, past twice that it must be,
 *  and only the band between is counted. */
function exceeds(text: string, cap: number): boolean {
  if (text.length <= cap) return false
  return text.length > 2 * cap || Array.from(text).length > cap
}

export interface ResearchSource {
  readonly url: string
  readonly title: string
  /** True when the page was actually read, not just listed. */
  readonly fetched: boolean
}

export interface ResearchSources {
  readonly callId: string
  /** The (redacted) query the server searched. */
  readonly question: string
  /** The cache answered: nothing was searched or billed this turn. */
  readonly cached: boolean
  /** What THIS turn spent. */
  readonly searches: number
  readonly pages: number
  readonly sources: readonly ResearchSource[]
}

type Fields = Record<string, unknown>

/** `value` as a plain object (not an array, not null), or null. Shared with the stream parser. */
export function record(value: unknown): Fields | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Fields)
    : null
}

/** Whether `value` is a whole number of at least zero. Shared with the stream parser. */
export function count(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function toSource(value: unknown): ResearchSource | null {
  const d = record(value)
  if (d === null) return null
  const { url, title, fetched } = d
  if (typeof url !== 'string' || typeof title !== 'string' || typeof fetched !== 'boolean') {
    return null
  }
  if (exceeds(url, MAX_SOURCE_URL) || exceeds(title, MAX_SOURCE_TITLE)) return null
  return { url, title, fetched }
}

function toSources(value: unknown): readonly ResearchSource[] | null {
  if (!Array.isArray(value) || value.length > MAX_RESEARCH_SOURCES) return null
  const sources = value.map(toSource)
  return sources.every((source): source is ResearchSource => source !== null) ? sources : null
}

/** The sources of a `research_sources` frame or a stored `attrs.research_sources`, or null when
 *  anything in it is unproven. Only the fields it names are kept. */
export function toResearchSources(data: unknown): ResearchSources | null {
  const d = record(data)
  if (d === null) return null
  const sources = toSources(d.sources)
  if (sources === null || !count(d.searches) || !count(d.pages)) return null
  if (typeof d.call_id !== 'string' || typeof d.question !== 'string') return null
  if (typeof d.cached !== 'boolean' || exceeds(d.question, MAX_QUESTION)) return null
  return {
    callId: d.call_id,
    question: d.question,
    cached: d.cached,
    searches: d.searches,
    pages: d.pages,
    sources
  }
}

/** The frame lands on the assistant item of the turn that streamed it. */
export function attachResearchSources(patch: Patch, research: ResearchSources): void {
  patch((item) => ({ ...item, researchSources: research }))
}
