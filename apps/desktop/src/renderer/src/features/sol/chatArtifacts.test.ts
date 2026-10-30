import { describe, expect, it } from 'vitest'
import { artifactExt, collectArtifacts, isTextArtifact } from './chatArtifacts'
import type { ChatArtifact, ChatItem } from './solChatStore'

const artifact = (id: string, title: string, mediaType = 'text/markdown'): ChatArtifact => ({
  artifactId: id,
  uri: `artifact://${id}`,
  mediaType,
  title,
  sourceTool: null,
  summary: null,
  filedTo: null
})
const item = (id: string, artifacts?: ChatArtifact[]): ChatItem => ({
  id,
  role: 'assistant',
  content: '',
  citations: [],
  trace: [],
  pending: false,
  error: null,
  confirmations: [],
  artifacts
})

describe('chatArtifacts', () => {
  it('collects artifacts across the transcript, deduped by id, in order', () => {
    const a = artifact('a', 'note.md')
    const b = artifact('b', 'check.csv', 'text/csv')
    expect(collectArtifacts([item('1', [a]), item('2'), item('3', [b, a])])).toEqual([a, b])
  })

  it('labels by the title extension, then the media subtype, capped at four characters', () => {
    expect(artifactExt({ title: 'note.md', mediaType: 'text/markdown' })).toBe('MD')
    expect(artifactExt({ title: 'patch.diff', mediaType: 'text/plain' })).toBe('DIFF')
    expect(artifactExt({ title: 'untitled', mediaType: 'image/svg+xml' })).toBe('SVG')
    expect(artifactExt({ title: 'archive.tar.gz', mediaType: 'application/gzip' })).toBe('GZ')
    expect(artifactExt({ title: 'x', mediaType: 'application/octet-stream' })).toBe('OCTE')
    expect(artifactExt({ title: '', mediaType: '' })).toBe('FILE')
  })

  it('knows which media types are copyable text', () => {
    expect(isTextArtifact('text/markdown')).toBe(true)
    expect(isTextArtifact('application/json')).toBe(true)
    expect(isTextArtifact('image/svg+xml')).toBe(true)
    expect(isTextArtifact('image/png')).toBe(false)
  })
})
