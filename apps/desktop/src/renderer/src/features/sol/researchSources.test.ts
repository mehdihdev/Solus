// SOLUSDEV-321 P1-T5: the web sources of a turn's research. ONE validator reads the live
// `research_sources` frame and the persisted `attrs.research_sources` of a reloaded turn; it is
// bounded, and anything unproven drops the whole payload (CLAUDE.md §7: parse defensively).
import { describe, expect, it } from 'vitest'
import {
  MAX_RESEARCH_SOURCES,
  MAX_SOURCE_TITLE,
  MAX_SOURCE_URL,
  attachResearchSources,
  toResearchSources
} from './researchSources'
import type { SolTurn } from './solApi'
import { blankItem, turnToSourcedItem } from './solChatItems'

const SOURCE = { url: 'https://docs.example.com/ov9281', title: 'OV9281 datasheet', fetched: true }
const FRAME = {
  call_id: 'c1',
  question: 'OV9281 supply voltage',
  cached: false,
  searches: 1,
  pages: 2,
  sources: [SOURCE, { url: 'https://blog.example.com/x', title: 'A blog', fetched: false }]
}

describe('toResearchSources', () => {
  it('reads a well-formed payload into a camel-cased value', () => {
    expect(toResearchSources(FRAME)).toEqual({
      callId: 'c1',
      question: 'OV9281 supply voltage',
      cached: false,
      searches: 1,
      pages: 2,
      sources: [
        { url: 'https://docs.example.com/ov9281', title: 'OV9281 datasheet', fetched: true },
        { url: 'https://blog.example.com/x', title: 'A blog', fetched: false }
      ]
    })
  })

  it('accepts exactly the bounds and an empty source list', () => {
    const edge = {
      ...FRAME,
      sources: Array.from({ length: MAX_RESEARCH_SOURCES }, (_, n) => ({
        url: `https://example.com/${n}`.padEnd(MAX_SOURCE_URL, 'a'),
        title: 'x'.repeat(MAX_SOURCE_TITLE),
        fetched: false
      }))
    }
    expect(toResearchSources(edge)?.sources).toHaveLength(MAX_RESEARCH_SOURCES)
    expect(toResearchSources({ ...FRAME, sources: [] })?.sources).toEqual([])
  })

  it.each([
    ['not an object', 'research'],
    ['null', null],
    ['an array', [FRAME]],
    ['a missing call id', { ...FRAME, call_id: undefined }],
    ['a non-string question', { ...FRAME, question: 7 }],
    ['a non-boolean cached', { ...FRAME, cached: 'no' }],
    ['a negative count', { ...FRAME, searches: -1 }],
    ['a fractional count', { ...FRAME, pages: 1.5 }],
    ['a non-number count', { ...FRAME, pages: '2' }],
    ['sources that are not a list', { ...FRAME, sources: 'https://x' }],
    [
      'more sources than the cap',
      { ...FRAME, sources: Array(MAX_RESEARCH_SOURCES + 1).fill(SOURCE) }
    ],
    ['a non-string url', { ...FRAME, sources: [{ ...SOURCE, url: 7 }] }],
    [
      'a url past the bound',
      { ...FRAME, sources: [{ ...SOURCE, url: `https://${'a'.repeat(MAX_SOURCE_URL)}` }] }
    ],
    ['a non-string title', { ...FRAME, sources: [{ ...SOURCE, title: null }] }],
    [
      'a title past the bound',
      { ...FRAME, sources: [{ ...SOURCE, title: 'x'.repeat(MAX_SOURCE_TITLE + 1) }] }
    ],
    ['a non-boolean fetched', { ...FRAME, sources: [{ ...SOURCE, fetched: 1 }] }],
    ['a source that is not an object', { ...FRAME, sources: ['https://x'] }]
  ])('drops the whole payload for %s', (_name, data) => {
    expect(toResearchSources(data)).toBeNull()
  })

  it('drops the whole payload when one source in the list is bad, never half of it', () => {
    expect(
      toResearchSources({ ...FRAME, sources: [SOURCE, { ...SOURCE, fetched: 'yes' }] })
    ).toBeNull()
  })

  it('keeps nothing but the fields it names', () => {
    const read = toResearchSources({
      ...FRAME,
      extra: 'x',
      sources: [{ ...SOURCE, html: '<b>x</b>' }]
    })
    expect(JSON.stringify(read)).not.toContain('<b>')
    expect(read).not.toHaveProperty('extra')
  })
})

describe('the bounds count code points, as the server does', () => {
  // An astral character is two UTF-16 units but ONE code point, and the server's `max_length`
  // counts code points: comparing `.length` would drop a payload the server allows.
  const astral = '\u{1F600}'
  const withSource = (field: 'title' | 'url', value: string): unknown => ({
    ...FRAME,
    sources: [{ ...SOURCE, [field]: value }]
  })

  it('accepts exactly the title cap in astral characters and rejects one more', () => {
    expect(astral.repeat(MAX_SOURCE_TITLE)).toHaveLength(2 * MAX_SOURCE_TITLE)
    expect(toResearchSources(withSource('title', astral.repeat(MAX_SOURCE_TITLE)))).not.toBeNull()
    expect(toResearchSources(withSource('title', astral.repeat(MAX_SOURCE_TITLE + 1)))).toBeNull()
  })

  it('does the same for a url and for the query', () => {
    const room = MAX_SOURCE_URL - 'https://'.length
    expect(toResearchSources(withSource('url', `https://${astral.repeat(room)}`))).not.toBeNull()
    expect(toResearchSources(withSource('url', `https://${astral.repeat(room + 1)}`))).toBeNull()
    expect(toResearchSources({ ...FRAME, question: astral.repeat(400) })).not.toBeNull()
    expect(toResearchSources({ ...FRAME, question: astral.repeat(401) })).toBeNull()
  })
})

describe('on a transcript item', () => {
  it('attachResearchSources sets the sources on the item the patch targets', () => {
    const research = toResearchSources(FRAME)
    if (research === null) throw new Error('fixture must validate')
    let item = blankItem('a1', 'assistant', '', true)
    attachResearchSources((fn) => {
      item = fn(item)
    }, research)
    expect(item.researchSources).toEqual(research)
    expect(item.pending).toBe(true) // nothing else about the item moves
  })

  const turn = (attrs: Record<string, unknown>): SolTurn => ({
    id: 't1',
    conversation_id: 'c1',
    role: 'assistant',
    content: 'AVDD is 2.8 V.',
    attrs,
    created_at: ''
  })

  it('a reloaded turn gets its sources from attrs.research_sources, through the same validator', () => {
    const item = turnToSourcedItem(turn({ research_sources: FRAME, tool_calls: 1 }))
    expect(item.researchSources).toEqual(toResearchSources(FRAME))
    expect(item).toMatchObject({ id: 't1', role: 'assistant', content: 'AVDD is 2.8 V.' })
  })

  it('a turn without, or with malformed, sources reloads exactly as it did before', () => {
    for (const attrs of [
      {},
      { research_sources: { ...FRAME, sources: 'x' } },
      { research_sources: 7 }
    ]) {
      expect(turnToSourcedItem(turn(attrs))).not.toHaveProperty('researchSources')
    }
  })
})
