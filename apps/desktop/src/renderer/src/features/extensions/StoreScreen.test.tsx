// SOLUSDEV-235 — the Store catalog page.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StoreScreen, INSTALLED_PREVIEW_COUNT } from './StoreScreen'
import { useExtensionsStore } from './extensionsStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as sourcesHook from '../project/useProjectSources'
import type { Source } from '../../lib/api/resources'

vi.mock('../project/useProjectSources', () => ({ useProjectSources: vi.fn() }))

function mockSources(status: sourcesHook.ProjectSourcesStatus, types: string[] = []): void {
  vi.mocked(sourcesHook.useProjectSources).mockReturnValue({
    status,
    sources: types.map((type) => ({ id: type, type }) as Source),
    actions: { refresh: vi.fn(), syncNow: vi.fn(), disconnect: vi.fn() }
  })
}

beforeEach(() => {
  useExtensionsStore.getState().reset()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Elegoo Robot Test' }, linked: true })
  mockSources('ready')
})

describe('StoreScreen', () => {
  it('asks for a project when none is open', () => {
    useWorkspaceStore.setState({ project: null })
    render(<StoreScreen />)
    expect(screen.getByText('Select a project')).toBeInTheDocument()
  })

  it('previews the installed set and expands to all of them', async () => {
    render(<StoreScreen />)
    expect(screen.getByRole('heading', { name: 'Store' })).toBeInTheDocument()
    const installed = screen.getByTestId('store-installed')
    expect(within(installed).getAllByText('INSTALLED')).toHaveLength(INSTALLED_PREVIEW_COUNT)
    await userEvent.click(screen.getByRole('button', { name: 'See all installed (7)' }))
    expect(within(installed).getAllByText('INSTALLED')).toHaveLength(7)
    await userEvent.click(screen.getByRole('button', { name: 'Show fewer' }))
    expect(within(installed).getAllByText('INSTALLED')).toHaveLength(INSTALLED_PREVIEW_COUNT)
  })

  it('suggests uninstalled extensions with their source requirements', () => {
    render(<StoreScreen />)
    const popular = screen.getByTestId('store-popular')
    expect(within(popular).getByText('BOM')).toBeInTheDocument()
    expect(within(popular).getAllByText('NEEDS EDA')).toHaveLength(2)
    expect(within(popular).getByText('NEEDS CANBUS')).toBeInTheDocument()
    expect(within(popular).getByText('NEEDS CAD|EDA')).toBeInTheDocument()
  })

  it('requirements follow what is actually connected', () => {
    mockSources('ready', ['kicad'])
    render(<StoreScreen />)
    const popular = screen.getByTestId('store-popular')
    expect(within(popular).getAllByText('AVAILABLE')).toHaveLength(3)
    expect(within(popular).getByText('NEEDS CANBUS')).toBeInTheDocument()
  })

  it('explains when source requirements cannot be evaluated', () => {
    mockSources('offline')
    render(<StoreScreen />)
    expect(screen.getByText(/can't see this project's sources/i)).toBeInTheDocument()
  })

  it('says when it is still checking sources rather than flashing unmet requirements as final', () => {
    mockSources('loading')
    render(<StoreScreen />)
    expect(screen.getByText(/Checking this project’s connected sources/)).toBeInTheDocument()
  })

  it('switches between grid and list layouts', async () => {
    render(<StoreScreen />)
    expect(screen.getByTestId('store-installed')).toHaveAttribute('data-layout', 'grid')
    await userEvent.click(screen.getByRole('radio', { name: 'List view' }))
    expect(screen.getByTestId('store-installed')).toHaveAttribute('data-layout', 'list')
  })

  it('opens an extension in detail and returns to the catalog', async () => {
    render(<StoreScreen />)
    await userEvent.click(screen.getByRole('button', { name: 'Open Experiments' }))
    expect(useExtensionsStore.getState().selectedId).toBe('experiments')
    expect(screen.getByRole('heading', { name: 'Experiments' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Permissions' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Back to Store' }))
    expect(screen.getByRole('heading', { name: 'Store' })).toBeInTheDocument()
  })

  it('falls back to the catalog for a stale selection', () => {
    useExtensionsStore.getState().select('gone')
    render(<StoreScreen />)
    expect(screen.getByRole('heading', { name: 'Store' })).toBeInTheDocument()
  })

  it('opens the create-extension dialog', async () => {
    render(<StoreScreen />)
    await userEvent.click(screen.getByRole('button', { name: /Create extension/ }))
    expect(screen.getByRole('heading', { name: 'Create an extension' })).toBeInTheDocument()
  })
})
