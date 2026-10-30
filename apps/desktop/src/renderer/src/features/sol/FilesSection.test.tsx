import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { SolusEntry } from '../../lib/api/resources'
import { emptySections, type SolusState } from '../graph/useSolusConfig'
import { FilesSection, solusFiles } from './FilesSection'

const entry = (over: Partial<SolusEntry>): SolusEntry => ({
  id: 'e1',
  section: 'documentation',
  subsection: null,
  kind: 'artifact',
  author: 'user',
  text: null,
  payload: null,
  name: 'clearance-spec.pdf',
  artifact_id: 'a1',
  entity_id: 'n1',
  media_type: 'application/pdf',
  size_bytes: 1024,
  created_by: null,
  created_at: '',
  updated_at: '',
  ...over
})

function state(over: Partial<SolusState> = {}): SolusState {
  return {
    status: 'ready',
    entityId: 's',
    sections: emptySections(),
    refetch: vi.fn(),
    ...over
  }
}

describe('FilesSection', () => {
  it('lists only file entries, across sections, with their ext label', () => {
    const sections = emptySections()
    sections.documentation = [entry({}), entry({ id: 'e2', kind: 'text', name: null })]
    sections.environment = [entry({ id: 'e3', name: 'mount-rev-c.png', media_type: 'image/png' })]
    expect(solusFiles(sections).map((e) => e.id)).toEqual(['e1', 'e3'])
    render(<FilesSection solus={state({ sections })} onUpload={vi.fn()} />)
    expect(screen.getByText('clearance-spec.pdf')).toBeInTheDocument()
    expect(screen.getByText('PDF')).toBeInTheDocument()
    expect(screen.getByText('PNG')).toBeInTheDocument()
  })

  it('uploads through the hidden file input and is honest when empty or offline', () => {
    const onUpload = vi.fn()
    const { rerender } = render(<FilesSection solus={state()} onUpload={onUpload} />)
    expect(screen.getByText(/SOL sees them by name/)).toBeInTheDocument()
    const file = new File(['x'], 'notes.md', { type: 'text/markdown' })
    fireEvent.change(screen.getByLabelText('Upload file or image'), { target: { files: [file] } })
    expect(onUpload).toHaveBeenCalledWith(file)
    rerender(<FilesSection solus={state({ status: 'offline' })} onUpload={onUpload} />)
    expect(screen.getByText('Unavailable offline.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+ Upload' })).toBeDisabled()
  })
})
