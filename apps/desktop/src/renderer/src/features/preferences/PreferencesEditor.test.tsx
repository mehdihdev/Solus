// SOLUSDEV-244 / HOME H3: the editor is pure — draft in, draft out — with a
// counter per field naming the cap that bounds the prompt.
import { emptyEngineeringPreferences } from '@solus/shared-types'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { PreferencesEditor } from './PreferencesEditor'

const INITIAL = { ...emptyEngineeringPreferences(), electrical: 'XT30 for power.' }

describe('PreferencesEditor', () => {
  it('renders six labelled textareas seeded from the document', () => {
    render(
      <PreferencesEditor
        initial={INITIAL}
        fieldCap={800}
        freeTextCap={2400}
        failed={false}
        onCancel={vi.fn()}
        onSave={vi.fn()}
      />
    )
    expect(screen.getAllByRole('textbox')).toHaveLength(6)
    expect(screen.getByLabelText('Electrical')).toHaveValue('XT30 for power.')
    expect(screen.getByLabelText('Anything else')).toHaveValue('')
    expect(screen.getByText('15 / 800')).toBeInTheDocument()
    expect(screen.getByText('0 / 2400')).toBeInTheDocument()
  })

  it('hands the edited draft to onSave and the untouched one is never mutated', async () => {
    const onSave = vi.fn()
    render(
      <PreferencesEditor
        initial={INITIAL}
        fieldCap={800}
        freeTextCap={2400}
        failed={false}
        onCancel={vi.fn()}
        onSave={onSave}
      />
    )
    await userEvent.type(screen.getByLabelText('Anything else'), 'Diagrams over prose.')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSave).toHaveBeenCalledWith({
      ...INITIAL,
      freeText: 'Diagrams over prose.'
    })
    expect(INITIAL.freeText).toBe('')
  })

  it('caps each field at its limit via maxLength', () => {
    render(
      <PreferencesEditor
        initial={INITIAL}
        fieldCap={800}
        freeTextCap={2400}
        failed
        onCancel={vi.fn()}
        onSave={vi.fn()}
      />
    )
    expect(screen.getByLabelText('Mechanical')).toHaveAttribute('maxlength', '800')
    expect(screen.getByLabelText('Anything else')).toHaveAttribute('maxlength', '2400')
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})
