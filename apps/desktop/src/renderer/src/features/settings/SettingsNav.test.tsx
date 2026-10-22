import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SettingsNav } from './SettingsNav'
import { SETTINGS_SECTIONS } from './settingsSections.constants'

function nav(
  overrides: Partial<Parameters<typeof SettingsNav>[0]> = {}
): Parameters<typeof SettingsNav>[0] {
  return {
    sections: SETTINGS_SECTIONS,
    query: '',
    onQuery: vi.fn(),
    attentionCount: 0,
    onJump: vi.fn(),
    ...overrides
  }
}

describe('SettingsNav', () => {
  it('lists every section under its group heading', () => {
    render(<SettingsNav {...nav()} />)
    for (const g of ['You', 'Workspace', 'System']) {
      expect(screen.getByText(g)).toBeInTheDocument()
    }
    for (const s of SETTINGS_SECTIONS) {
      expect(screen.getByRole('button', { name: s.title })).toBeInTheDocument()
    }
  })

  it('jumps to a section by id — a button, never a hash link the router would eat', async () => {
    const props = nav()
    render(<SettingsNav {...props} />)
    await userEvent.click(screen.getByRole('button', { name: 'Appearance' }))
    expect(props.onJump).toHaveBeenCalledWith('appearance')
    expect(screen.queryAllByRole('link')).toHaveLength(0)
  })

  it('reports what the user types into Find a setting', async () => {
    const props = nav()
    render(<SettingsNav {...props} />)
    await userEvent.type(screen.getByRole('searchbox', { name: 'Find a setting' }), 't')
    expect(props.onQuery).toHaveBeenCalledWith('t')
  })

  it('hides group headings with nothing left to show', () => {
    render(
      <SettingsNav {...nav({ sections: SETTINGS_SECTIONS.filter((s) => s.id === 'about') })} />
    )
    expect(screen.queryByText('You')).toBeNull()
    expect(screen.getByText('System')).toBeInTheDocument()
  })

  it('shows a Needs attention entry with its count only when something needs the user', async () => {
    const { rerender } = render(<SettingsNav {...nav()} />)
    expect(screen.queryByRole('button', { name: /Needs attention/ })).toBeNull()
    const props = nav({ attentionCount: 2 })
    rerender(<SettingsNav {...props} />)
    const entry = screen.getByRole('button', { name: /Needs attention/ })
    expect(entry).toHaveTextContent('2')
    await userEvent.click(entry)
    expect(props.onJump).toHaveBeenCalledWith('attention')
  })

  it('marks the section in view as current', () => {
    render(<SettingsNav {...nav({ activeId: 'appearance' })} />)
    expect(screen.getByRole('button', { name: 'Appearance' })).toHaveAttribute(
      'aria-current',
      'true'
    )
    expect(screen.getByRole('button', { name: 'SOL' })).not.toHaveAttribute('aria-current')
  })

  it('says when no setting matches', () => {
    render(<SettingsNav {...nav({ sections: [], query: 'zzz' })} />)
    expect(screen.getByText(/No settings match/)).toBeInTheDocument()
  })
})
