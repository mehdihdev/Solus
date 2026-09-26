import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SourceRevisionPicker } from './SourceRevisionPicker'

const mocks = vi.hoisted(() => ({ list: vi.fn(), view: vi.fn(), select: vi.fn(), reset: vi.fn() }))
vi.mock('../../lib/api/resources.revisions', () => ({
  listSourceRevisions: mocks.list,
  getSourceView: mocks.view,
  selectSourceView: mocks.select,
  resetSourceView: mocks.reset
}))

const defaultView = {
  base_source_id: 'source',
  source_id: 'source',
  status: 'default',
  branch: 'main',
  commit: 'a'.repeat(40),
  error: null
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.list.mockResolvedValue({
    supported: true,
    kind: 'git_branch',
    items: [
      { name: 'main', commit: 'a'.repeat(40) },
      { name: 'vlfh_tsfm', commit: 'b'.repeat(40) }
    ],
    next_page: null
  })
  mocks.view.mockResolvedValue(defaultView)
})

describe('personal repository branch picker', () => {
  it('shows branches and selects a personal view without changing shared source configuration', async () => {
    const changed = vi.fn()
    const next = { ...defaultView, status: 'ready', source_id: 'snapshot', branch: 'vlfh_tsfm' }
    mocks.select.mockResolvedValue(next)
    render(<SourceRevisionPicker projectId="project" sourceId="source" onChanged={changed} />)
    fireEvent.change(await screen.findByRole('combobox', { name: 'Branch' }), {
      target: { value: 'vlfh_tsfm' }
    })
    await waitFor(() => expect(mocks.select).toHaveBeenCalledWith('project', 'source', 'vlfh_tsfm'))
    await waitFor(() => expect(changed).toHaveBeenCalledOnce())
    expect(screen.getByText(/only your view/i)).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Branch' })).toHaveValue('vlfh_tsfm')
  })

  it('loads additional branch pages without dropping previous choices', async () => {
    mocks.list
      .mockResolvedValueOnce({
        supported: true,
        kind: 'git_branch',
        items: [{ name: 'main', commit: 'a' }],
        next_page: 2
      })
      .mockResolvedValueOnce({
        supported: true,
        kind: 'git_branch',
        items: [{ name: 'vlfh_tsfm', commit: 'b' }],
        next_page: null
      })
    render(<SourceRevisionPicker projectId="project" sourceId="source" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Load more branches' }))
    expect(await screen.findByRole('option', { name: 'vlfh_tsfm' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'main' })).toBeInTheDocument()
  })

  it('keeps the active view visible when acquisition fails', async () => {
    mocks.select.mockResolvedValue({
      ...defaultView,
      status: 'failed',
      error: 'Branch is unavailable'
    })
    render(<SourceRevisionPicker projectId="project" sourceId="source" />)
    fireEvent.change(await screen.findByRole('combobox', { name: 'Branch' }), {
      target: { value: 'vlfh_tsfm' }
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('Branch is unavailable')
    expect(screen.getByRole('combobox', { name: 'Branch' })).toHaveValue('main')
  })

  it('discards a late branch response when the selected repository changes', async () => {
    let finish!: (value: unknown) => void
    mocks.list.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
    const rendered = render(<SourceRevisionPicker projectId="project" sourceId="source" />)
    rendered.rerender(<SourceRevisionPicker projectId="project" sourceId="second" />)
    await screen.findByRole('option', { name: 'vlfh_tsfm' })
    await act(async () =>
      finish({
        supported: true,
        kind: 'git_branch',
        items: [{ name: 'stale', commit: 'c' }],
        next_page: null
      })
    )
    expect(screen.queryByRole('option', { name: 'stale' })).not.toBeInTheDocument()
  })

  it('does not invent branch controls for unsupported providers', async () => {
    mocks.list.mockResolvedValue({ supported: false, kind: null, items: [], next_page: null })
    render(<SourceRevisionPicker projectId="project" sourceId="source" />)
    await waitFor(() => expect(screen.queryByRole('combobox')).not.toBeInTheDocument())
  })
})

it('does not let an in-flight pending poll replace a reset', async () => {
  vi.useFakeTimers()
  try {
    const changed = vi.fn()
    let finishPoll!: (view: unknown) => void
    let finishReset!: (view: unknown) => void
    mocks.view.mockResolvedValueOnce({ ...defaultView, status: 'pending' }).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishPoll = resolve
        })
    )
    mocks.reset.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishReset = resolve
        })
    )
    render(<SourceRevisionPicker projectId="project" sourceId="source" onChanged={changed} />)
    await act(async () => {
      await Promise.resolve()
    })
    await act(() => vi.advanceTimersByTimeAsync(2000))
    fireEvent.click(screen.getByRole('button', { name: 'Use project default' }))
    await act(async () =>
      finishPoll({ ...defaultView, status: 'ready', source_id: 'snapshot', branch: 'vlfh_tsfm' })
    )
    expect(changed).not.toHaveBeenCalled()
    await act(async () => finishReset(defaultView))
    expect(changed).toHaveBeenCalledOnce()
  } finally {
    vi.useRealTimers()
  }
})

it('refreshes a stale graph when reopening a completed branch selection', async () => {
  const changed = vi.fn()
  mocks.view.mockResolvedValue({
    ...defaultView,
    status: 'ready',
    source_id: 'snapshot',
    branch: 'vlfh_tsfm'
  })
  render(
    <SourceRevisionPicker
      projectId="project"
      sourceId="source"
      activeSourceId="source"
      onChanged={changed}
    />
  )
  await waitFor(() => expect(changed).toHaveBeenCalledOnce())
})

it('resumes pending acquisition polling when resetting the view fails', async () => {
  vi.useFakeTimers()
  try {
    const changed = vi.fn()
    mocks.view
      .mockResolvedValueOnce({ ...defaultView, status: 'pending' })
      .mockResolvedValueOnce({
        ...defaultView,
        status: 'ready',
        source_id: 'snapshot',
        branch: 'vlfh_tsfm'
      })
    mocks.reset.mockRejectedValueOnce(new Error('Network unavailable'))
    render(<SourceRevisionPicker projectId="project" sourceId="source" onChanged={changed} />)
    await act(async () => {
      await Promise.resolve()
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Use project default' }))
    })
    expect(screen.getByRole('alert')).toHaveTextContent('Could not select this branch')
    await act(() => vi.advanceTimersByTimeAsync(2000))
    expect(changed).toHaveBeenCalledOnce()
    expect(screen.getByRole('combobox', { name: 'Branch' })).toHaveValue('vlfh_tsfm')
  } finally {
    vi.useRealTimers()
  }
})
