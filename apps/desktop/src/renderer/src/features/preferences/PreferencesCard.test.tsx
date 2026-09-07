// SOLUSDEV-244 / HOME H3: the "How you engineer" card on Home — a document the
// user writes (five sections + notes), not a settings screen. View → editor →
// save with revert-on-failure; honest read-only and unavailable states.
import { emptyEngineeringPreferences, type EngineeringPreferences } from '@solus/shared-types'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as bridge from '../../lib/desktopBridge'
import { PreferencesCard } from './PreferencesCard'
import { usePreferencesStore } from './preferencesStore'

vi.mock('../../lib/desktopBridge', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/desktopBridge')>()
  return { ...actual, getDesktopPreferencesBridge: vi.fn() }
})
const getBridge = vi.mocked(bridge.getDesktopPreferencesBridge)

const DOC: EngineeringPreferences = {
  ...emptyEngineeringPreferences(),
  electrical: 'Prefer 0.1 mm clearance minimum on all boards.',
  unitsStandards: 'SI units.'
}

function fakeBridge(
  doc: EngineeringPreferences,
  readOnly = false
): { write: ReturnType<typeof vi.fn> } {
  const write = vi.fn(async () => ({ ok: true }))
  getBridge.mockReturnValue({ read: vi.fn(async () => ({ preferences: doc, readOnly })), write })
  return { write }
}

beforeEach(() => {
  vi.clearAllMocks()
  usePreferencesStore.getState().reset()
})

describe('PreferencesCard', () => {
  it('shows the written sections and hides the empty ones', async () => {
    fakeBridge(DOC)
    render(<PreferencesCard />)
    expect(await screen.findByText(DOC.electrical)).toBeInTheDocument()
    expect(screen.getByText('Electrical')).toBeInTheDocument()
    expect(screen.getByText('Units and standards')).toBeInTheDocument()
    expect(screen.queryByText('Mechanical')).toBeNull()
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
    expect(screen.getByText(/shared by everyone who signs in here/)).toBeInTheDocument()
  })

  it('invites the first write when nothing is saved yet', async () => {
    fakeBridge(emptyEngineeringPreferences())
    render(<PreferencesCard />)
    expect(await screen.findByRole('button', { name: '+ Add' })).toBeInTheDocument()
    expect(screen.getByText(/SOL follows these on every turn/)).toBeInTheDocument()
  })

  it('edits every section as free text and saves through the bridge', async () => {
    const b = fakeBridge(DOC)
    render(<PreferencesCard />)
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    const mechanical = screen.getByLabelText('Mechanical')
    await userEvent.type(mechanical, 'Metric fasteners only.')
    // Counters name the per-field cap; nothing here is a toggle.
    expect(screen.getAllByText(/\/ 800/).length).toBe(5)
    expect(screen.getByText(/\/ 2400/)).toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(b.write).toHaveBeenCalledWith(
        expect.objectContaining({
          mechanical: 'Metric fasteners only.',
          electrical: DOC.electrical
        })
      )
    )
    expect(await screen.findByText('Metric fasteners only.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Mechanical')).toBeNull()
  })

  it('keeps the editor open with an error when the save fails', async () => {
    const b = fakeBridge(DOC)
    b.write.mockResolvedValue({ ok: false })
    render(<PreferencesCard />)
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    await userEvent.type(screen.getByLabelText('Code style'), 'C++17.')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Couldn.t save/)
    expect(screen.getByLabelText('Code style')).toHaveValue('C++17.')
  })

  it('cancel discards the draft', async () => {
    fakeBridge(DOC)
    render(<PreferencesCard />)
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    await userEvent.type(screen.getByLabelText('Documentation'), 'drop me')
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByText('drop me')).toBeNull()
    expect(screen.getByText(DOC.electrical)).toBeInTheDocument()
  })

  it('is read-only when a newer Solus wrote the file', async () => {
    fakeBridge(DOC, true)
    render(<PreferencesCard />)
    expect(await screen.findByText(/newer version of Solus/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()
  })

  it('is honest outside the desktop app', async () => {
    getBridge.mockReturnValue(null)
    render(<PreferencesCard />)
    expect(await screen.findByText(/desktop app/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()
  })
})
