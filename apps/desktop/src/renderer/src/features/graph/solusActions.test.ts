import { describe, it, expect, vi } from 'vitest'
import type { SolusEntry } from '../../lib/api/resources'
import { askSolMessage, entryMenuItems, formatSize, sectionCountLabel } from './solusActions'

function entry(over: Partial<SolusEntry>): SolusEntry {
  return {
    id: 'e1',
    section: 'code',
    kind: 'text',
    author: 'user',
    text: 'x',
    payload: null,
    name: null,
    artifact_id: null,
    entity_id: null,
    media_type: null,
    size_bytes: null,
    created_by: null,
    created_at: '',
    updated_at: '',
    ...over
  }
}

describe('solusActions pure helpers', () => {
  it('formats counts, sizes and the Ask-SOL turn', () => {
    expect(sectionCountLabel(0)).toBe('EMPTY')
    expect(sectionCountLabel(3)).toBe('3')
    expect(formatSize(null)).toBe('')
    expect(formatSize(512)).toBe('512 B')
    expect(formatSize(2048)).toBe('2.0 KB')
    expect(formatSize(3 * 1024 * 1024)).toBe('3.0 MB')
    expect(askSolMessage('Code environment', ' cuda version ')).toBe(
      'Find for .solus › Code environment: cuda version'
    )
  })

  it('offers Edit for notes only — never for artifacts or config entries', () => {
    const labels = (item: SolusEntry): string[] =>
      entryMenuItems(item, vi.fn(), vi.fn()).map((i) => i.label)
    expect(labels(entry({}))).toEqual(['Edit', 'Delete'])
    expect(labels(entry({ kind: 'artifact' }))).toEqual(['Delete'])
    expect(labels(entry({ kind: 'config', payload: { type: 'venv' } }))).toEqual(['Delete'])
  })
})
