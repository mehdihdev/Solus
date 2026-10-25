import { describe, it, expect, vi } from 'vitest'
import type { SolusEntry } from '../../lib/api/resources'
import {
  askSolMessage,
  entryMenuItems,
  formatSize,
  isHardwareConfig,
  sectionCountLabel,
  sectionMenuItems,
  targetLabel
} from './solusActions'

function entry(over: Partial<SolusEntry>): SolusEntry {
  return {
    id: 'e1',
    section: 'environment',
    subsection: null,
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
    expect(askSolMessage('Environment', ' cuda version ')).toBe(
      'Find for .solus › Environment: cuda version'
    )
  })

  it('names the subsection in the Ask-SOL turn and the menu target', () => {
    expect(targetLabel('environment', 'software')).toBe('Environment › software')
    expect(targetLabel('errors', null)).toBe('Error logging')
    expect(isHardwareConfig(entry({ kind: 'config', subsection: 'hardware' }))).toBe(true)
    expect(isHardwareConfig(entry({ kind: 'config', subsection: 'software' }))).toBe(false)
    expect(isHardwareConfig(entry({ kind: 'text', subsection: 'hardware' }))).toBe(false)
    const onImport = vi.fn()
    const onCompose = vi.fn()
    const items = sectionMenuItems('documentation', false, onImport, onCompose, 'guides')
    items[0].onSelect()
    expect(onImport).toHaveBeenCalledWith('documentation', 'guides')
    items[2].onSelect()
    expect(onCompose).toHaveBeenCalledWith({
      section: 'documentation',
      subsection: 'guides',
      kind: 'type'
    })
  })

  it('offers no section actions on history or members — they own no hand-written rows', () => {
    expect(sectionMenuItems('history', false, vi.fn(), vi.fn())).toEqual([])
    expect(sectionMenuItems('members', false, vi.fn(), vi.fn())).toEqual([])
    expect(sectionMenuItems('errors', false, vi.fn(), vi.fn())).toHaveLength(3)
  })

  it('offers Edit for notes only — never for artifacts or config entries', () => {
    const labels = (item: SolusEntry): string[] =>
      entryMenuItems(item, vi.fn(), vi.fn()).map((i) => i.label)
    expect(labels(entry({}))).toEqual(['Edit', 'Delete'])
    expect(labels(entry({ kind: 'artifact' }))).toEqual(['Delete'])
    expect(labels(entry({ kind: 'config', payload: { type: 'venv' } }))).toEqual(['Delete'])
  })
})
