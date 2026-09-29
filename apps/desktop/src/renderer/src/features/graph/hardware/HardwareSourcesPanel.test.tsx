import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useAuthStore } from '../../../store/authStore'
import { HardwareSourcesPanel } from './HardwareSourcesPanel'

const PROJECT = '00000000-0000-4000-8000-000000000001'
const ACCOUNT = '00000000-0000-4000-8000-000000000002'
const REF = '00000000-0000-4000-8000-000000000003'
const source = { sourceRef: REF, contentSha256: 'a'.repeat(64), displayName: 'calibration.json' }
const list = vi.fn()
const pick = vi.fn()
const recheck = vi.fn()
beforeEach(() => {
  useAuthStore.setState({
    accessToken: 'fixture-session',
    user: { email: 'fixture@example.invalid' }
  })
  list.mockResolvedValue({
    ok: true,
    value: { projectId: PROJECT, accountId: ACCOUNT, sources: [] }
  })
  pick.mockResolvedValue({ ok: true, value: { projectId: PROJECT, accountId: ACCOUNT, source } })
  recheck.mockResolvedValue({ ok: false, reason: 'source_changed' })
  vi.stubGlobal('solus', { hardware: { sources: { list, pick, recheck } } })
})
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

it.each([
  'Verify calibration.json',
  'Relink calibration.json',
  'Choose local file',
  'Refresh sources'
])('invalidates review before %s', async (action) => {
  list.mockResolvedValue({
    ok: true,
    value: { projectId: PROJECT, accountId: ACCOUNT, sources: [source] }
  })
  const changed = vi.fn()
  const selected = vi.fn()
  render(
    <HardwareSourcesPanel
      projectId={PROJECT}
      mode="Guide"
      onSourceChange={changed}
      onSelect={selected}
    />
  )
  fireEvent.click(await screen.findByRole('button', { name: 'Select calibration.json' }))
  expect(selected).toHaveBeenCalledWith(`source:${REF}`)
  fireEvent.click(screen.getByRole('button', { name: action }))
  expect(changed).toHaveBeenCalledOnce()
  await act(async () => undefined)
})

it('relinks a shared opaque reference using only its bare UUID', async () => {
  render(<HardwareSourcesPanel projectId={PROJECT} mode="Guide" sourceRefs={[`source:${REF}`]} />)
  // The button renders disabled while the initial list() load is in flight; a
  // click then is a no-op. Wait until it is live — a slow CI runner lost the race.
  const relink = await screen.findByRole('button', { name: 'Relink source 1' })
  await waitFor(() => expect(relink).toBeEnabled(), { timeout: 5_000 })
  fireEvent.click(relink)
  await waitFor(() => expect(pick).toHaveBeenCalledWith({ sourceRef: REF }))
  expect(await screen.findByText('calibration.json')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Verify calibration.json' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('changed')
  expect(recheck).toHaveBeenCalledWith(REF)
})

it('never calls the API or invents verification when MAIN is absent', async () => {
  vi.stubGlobal('solus', undefined)
  render(<HardwareSourcesPanel projectId={PROJECT} mode="Expert" />)
  expect(await screen.findByText(/desktop app/i)).toBeInTheDocument()
  expect(list).not.toHaveBeenCalled()
})

it('discards a picker completion after project A to B to A', async () => {
  let finish!: (value: unknown) => void
  pick.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const view = render(<HardwareSourcesPanel projectId={PROJECT} mode="Guide" />)
  const choose = await screen.findByRole('button', { name: 'Choose local file' })
  await waitFor(() => expect(choose).toBeEnabled())
  fireEvent.click(choose)
  await waitFor(() => expect(pick).toHaveBeenCalled())
  view.rerender(<HardwareSourcesPanel projectId={REF} mode="Guide" />)
  view.rerender(<HardwareSourcesPanel projectId={PROJECT} mode="Guide" />)
  await act(async () =>
    finish({ ok: true, value: { projectId: PROJECT, accountId: ACCOUNT, source } })
  )
  expect(screen.queryByText('calibration.json')).not.toBeInTheDocument()
})

it('discards an old account result even when the token later returns', async () => {
  let finish!: (value: unknown) => void
  pick.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  render(<HardwareSourcesPanel projectId={PROJECT} mode="Guide" />)
  const choose = await screen.findByRole('button', { name: 'Choose local file' })
  await waitFor(() => expect(choose).toBeEnabled())
  fireEvent.click(choose)
  await waitFor(() => expect(pick).toHaveBeenCalled())
  act(() => {
    useAuthStore.setState({ accessToken: null })
    useAuthStore.setState({ accessToken: 'fixture-session' })
  })
  await act(async () =>
    finish({ ok: true, value: { projectId: PROJECT, accountId: ACCOUNT, source } })
  )
  expect(screen.queryByText('calibration.json')).not.toBeInTheDocument()
})

it('hides the prior project sources before the next list completes', async () => {
  list.mockResolvedValueOnce({
    ok: true,
    value: { projectId: PROJECT, accountId: ACCOUNT, sources: [source] }
  })
  const view = render(<HardwareSourcesPanel projectId={PROJECT} mode="Guide" />)
  expect(await screen.findByText('calibration.json')).toBeInTheDocument()
  list.mockImplementationOnce(() => new Promise(() => {}))
  view.rerender(<HardwareSourcesPanel projectId={REF} mode="Guide" />)
  expect(screen.queryByText('calibration.json')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Choose local file' })).toBeDisabled()
})

it('clears loaded files and prevents actions while refreshing', async () => {
  list.mockResolvedValueOnce({
    ok: true,
    value: { projectId: PROJECT, accountId: ACCOUNT, sources: [source] }
  })
  render(<HardwareSourcesPanel projectId={PROJECT} mode="Guide" />)
  expect(await screen.findByText('calibration.json')).toBeInTheDocument()
  let finish!: (value: unknown) => void
  list.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  fireEvent.click(screen.getByRole('button', { name: 'Refresh sources' }))
  expect(screen.queryByText('calibration.json')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Choose local file' })).toBeDisabled()
  await act(async () =>
    finish({ ok: true, value: { projectId: PROJECT, accountId: ACCOUNT, sources: [] } })
  )
  expect(screen.getByRole('button', { name: 'Choose local file' })).toBeEnabled()
})
