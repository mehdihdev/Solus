import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LocalProjectBinding } from './LocalProjectBinding'
import { updateSource, type Source } from '../../lib/api/resources'
import { useSettingsStore } from '../../store/settingsStore'

vi.mock('../../lib/api/resources', () => ({ updateSource: vi.fn() }))

const SOURCE: Source = {
  id: 's1',
  project_id: 'p1',
  type: 'kicad',
  name: 'Divider',
  status: 'connected',
  config: {},
  account_login: null,
  last_synced_at: null,
  last_error: null,
  created_at: '',
  updated_at: ''
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(updateSource).mockResolvedValue(SOURCE)
  useSettingsStore.setState({ solMode: 'Guide' })
})

async function open(current = '', onSaved = vi.fn()): Promise<void> {
  render(
    <LocalProjectBinding
      projectId="p1"
      source={{ ...SOURCE, config: { project_path: current } }}
      onSaved={onSaved}
    />
  )
  await userEvent.click(screen.getByRole('button', { name: /project (file|link)/i }))
}

describe('LocalProjectBinding', () => {
  it('prefills and saves only a relative binding, then reports configuration saved', async () => {
    const onSaved = vi.fn()
    await open('old.kicad_pro', onSaved)
    const input = screen.getByLabelText('Project file path')
    expect(input).toHaveValue('old.kicad_pro')
    fireEvent.change(input, { target: { value: 'circuit/divider.kicad_pro' } })
    await userEvent.click(screen.getByRole('button', { name: 'Save project link' }))
    await waitFor(() =>
      expect(updateSource).toHaveBeenCalledWith('p1', 's1', {
        config: { project_path: 'circuit/divider.kicad_pro' }
      })
    )
    expect(onSaved).toHaveBeenCalledOnce()
    expect(screen.getByRole('status')).toHaveTextContent('Project link saved')
  })

  it.each([
    '',
    '/outside.kicad_pro',
    '../out.kicad_pro',
    'a/../out.kicad_pro',
    'a//b.kicad_pro',
    'a\\b.kicad_pro',
    'C:/out.kicad_pro',
    'a\tb.kicad_pro',
    'sheet.kicad_sch',
    'x'.repeat(513) + '.kicad_pro'
  ])('refuses invalid binding %s without a PATCH', async (path) => {
    await open()
    fireEvent.change(screen.getByLabelText('Project file path'), { target: { value: path } })
    await userEvent.click(screen.getByRole('button', { name: 'Save project link' }))
    expect(updateSource).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('cancel sends no request', async () => {
    await open()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(updateSource).not.toHaveBeenCalled()
    expect(screen.queryByLabelText('Project file path')).not.toBeInTheDocument()
  })

  it('keeps a failed save editable without exposing the raw error', async () => {
    vi.mocked(updateSource).mockRejectedValue(new Error('private backend detail'))
    await open('a.kicad_pro')
    await userEvent.click(screen.getByRole('button', { name: 'Save project link' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save')
    expect(screen.getByLabelText('Project file path')).toBeEnabled()
    expect(screen.queryByText('private backend detail')).not.toBeInTheDocument()
  })

  it('prevents duplicate submission while the PATCH is pending', async () => {
    let finish!: (source: Source) => void
    vi.mocked(updateSource).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve
      })
    )
    await open('a.kicad_pro')
    await userEvent.dblClick(screen.getByRole('button', { name: 'Save project link' }))
    expect(updateSource).toHaveBeenCalledOnce()
    expect(screen.getByLabelText('Project file path')).toBeDisabled()
    finish(SOURCE)
    await screen.findByRole('status')
  })

  it('uses Expert guidance while retaining the workspace boundary', async () => {
    useSettingsStore.setState({ solMode: 'Expert' })
    await open()
    expect(screen.getByText(/Relative to this project’s linked local folder/)).toBeInTheDocument()
  })
})
