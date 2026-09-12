import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  type RenderResult
} from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '../../../lib/api/envelope.types'
import {
  getEntityHardwareConfig,
  putEntityHardwareConfig,
  type EntityHardwareConfigOut
} from '../../../lib/api/hardware'
import { useAuthStore } from '../../../store/authStore'
import { HardwareConfigPanel } from './HardwareConfigPanel'

vi.mock('../../../lib/api/hardware', () => ({
  getEntityHardwareConfig: vi.fn(),
  putEntityHardwareConfig: vi.fn()
}))
vi.mock('./HardwareSourcesPanel', () => ({
  HardwareSourcesPanel: () => <div>Private sources</div>
}))
const config = {
  schema_version: 2 as const,
  entity_id: 'owner',
  component: { lifecycle: 'planned' as const },
  provenance: { component: { by: 'repo' as const, source: 'repo:fixture' } }
}
const saved = { entity_id: 'owner', entry_id: 'entry', config, version: 3 }
beforeEach(() => {
  useAuthStore.setState({
    accessToken: 'fixture-session',
    user: { email: 'fixture@example.invalid' }
  })
  vi.mocked(getEntityHardwareConfig).mockResolvedValue(saved)
  vi.mocked(putEntityHardwareConfig).mockResolvedValue({ ...saved, version: 4 })
})
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('reads the configured subject and saves changed fields with an expected version', async () => {
  render(<HardwareConfigPanel projectId="project" entityId="owner" online />)
  const editor = await screen.findByRole('textbox', { name: 'Hardware configuration' })
  expect(getEntityHardwareConfig).toHaveBeenCalledWith('project', 'owner')
  fireEvent.change(editor, {
    target: { value: JSON.stringify({ ...config, component: { lifecycle: 'installed' } }) }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }))
  await waitFor(() =>
    expect(putEntityHardwareConfig).toHaveBeenCalledWith(
      'project',
      'owner',
      expect.objectContaining({
        component: { lifecycle: 'installed' },
        provenance: expect.objectContaining({ 'component.lifecycle': { by: 'user' } })
      }),
      3
    )
  )
})

it('does not create an absent config until the user explicitly saves', async () => {
  vi.mocked(getEntityHardwareConfig).mockResolvedValue({
    entity_id: 'owner',
    entry_id: null,
    version: 0,
    config: null
  })
  render(<HardwareConfigPanel projectId="project" entityId="owner" online />)
  expect(await screen.findByText(/No saved configuration/)).toBeInTheDocument()
  expect(putEntityHardwareConfig).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }))
  await waitFor(() =>
    expect(putEntityHardwareConfig).toHaveBeenCalledWith(
      'project',
      'owner',
      expect.objectContaining({ entity_id: 'owner', schema_version: 2 }),
      0
    )
  )
})

it('retains the draft on version conflict and offers reload', async () => {
  vi.mocked(putEntityHardwareConfig).mockRejectedValue(
    new ApiError(409, 'config_conflict', 'stale')
  )
  render(<HardwareConfigPanel projectId="project" entityId="owner" online />)
  const editor = await screen.findByRole('textbox', { name: 'Hardware configuration' })
  const draft = JSON.stringify({ ...config, component: { lifecycle: 'installed' } })
  fireEvent.change(editor, { target: { value: draft } })
  fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('changed')
  expect(editor).toHaveValue(draft)
  expect(screen.getByRole('button', { name: 'Reload configuration' })).toBeEnabled()
})

it('rejects private paths locally before calling the API', async () => {
  render(<HardwareConfigPanel projectId="project" entityId="owner" online />)
  const editor = await screen.findByRole('textbox', { name: 'Hardware configuration' })
  fireEvent.change(editor, {
    target: {
      value: JSON.stringify({
        ...config,
        component: { calibration: { source: '/private/calibration.json' } }
      })
    }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('local file picker')
  expect(putEntityHardwareConfig).not.toHaveBeenCalled()
})

type Scope = 'entity' | 'project' | 'account'
function cycleScope(view: RenderResult, scope: Scope): void {
  if (scope === 'account') {
    const initial = useAuthStore.getState()
    act(() => {
      useAuthStore.setState({
        accessToken: 'other-fixture-session',
        user: { email: 'other@example.invalid' }
      })
      useAuthStore.setState({ accessToken: initial.accessToken, user: initial.user })
    })
  } else {
    view.rerender(
      <HardwareConfigPanel
        projectId={scope === 'project' ? 'other-project' : 'project'}
        entityId={scope === 'entity' ? 'other-owner' : 'owner'}
        online
      />
    )
    view.rerender(<HardwareConfigPanel projectId="project" entityId="owner" online />)
  }
}

function pendingConfig(): {
  promise: Promise<EntityHardwareConfigOut>
  resolve: (value: EntityHardwareConfigOut) => void
} {
  let resolve!: (value: EntityHardwareConfigOut) => void
  const promise = new Promise<EntityHardwareConfigOut>((yes) => {
    resolve = yes
  })
  return { promise, resolve }
}

const fresh: EntityHardwareConfigOut = {
  ...saved,
  version: 8,
  config: { ...config, component: { lifecycle: 'live' } }
}

it.each(['entity', 'project', 'account'] as const)(
  'ignores late GET after %s A to B to A and preserves the new draft/version',
  async (scope) => {
    const pending = pendingConfig()
    vi.mocked(getEntityHardwareConfig).mockResolvedValue(fresh).mockReturnValueOnce(pending.promise)
    const view = render(<HardwareConfigPanel projectId="project" entityId="owner" online />)
    expect(getEntityHardwareConfig).toHaveBeenCalledOnce()
    cycleScope(view, scope)
    const editor = await screen.findByRole('textbox', { name: 'Hardware configuration' })
    const draft = JSON.stringify({ ...config, component: { lifecycle: 'installed' } })
    fireEvent.change(editor, { target: { value: draft } })
    await act(async () => pending.resolve(saved))
    expect(editor).toHaveValue(draft)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }))
    await waitFor(() =>
      expect(putEntityHardwareConfig).toHaveBeenCalledWith('project', 'owner', expect.anything(), 8)
    )
  }
)

it.each(['entity', 'project', 'account'] as const)(
  'ignores late PUT after %s A to B to A without reviving the old draft or save status',
  async (scope) => {
    const pending = pendingConfig()
    vi.mocked(putEntityHardwareConfig).mockReturnValueOnce(pending.promise)
    const view = render(<HardwareConfigPanel projectId="project" entityId="owner" online />)
    const editor = await screen.findByRole('textbox', { name: 'Hardware configuration' })
    fireEvent.change(editor, {
      target: { value: JSON.stringify({ ...config, component: { lifecycle: 'installed' } }) }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }))
    await waitFor(() => expect(putEntityHardwareConfig).toHaveBeenCalledOnce())
    vi.mocked(getEntityHardwareConfig).mockResolvedValue(fresh)
    cycleScope(view, scope)
    const currentEditor = await screen.findByRole('textbox', { name: 'Hardware configuration' })
    expect(JSON.parse((currentEditor as HTMLTextAreaElement).value).component.lifecycle).toBe(
      'live'
    )
    await act(async () => pending.resolve({ ...saved, version: 4 }))
    expect(JSON.parse((currentEditor as HTMLTextAreaElement).value).component.lifecycle).toBe(
      'live'
    )
    expect(screen.queryByText('Configuration saved.')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save configuration' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }))
    await waitFor(() =>
      expect(putEntityHardwareConfig).toHaveBeenLastCalledWith(
        'project',
        'owner',
        expect.anything(),
        8
      )
    )
  }
)
