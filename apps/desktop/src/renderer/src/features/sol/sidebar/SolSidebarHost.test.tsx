// SOLUSDEV-327 — the docked SOL sidebar (sol-sidebar.md): per-screen open state, the context
// greeting and chips, the header's pop-out / expand / close, ⌘J, Escape, width and fit.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import * as solApi from '../solApi'
import * as resources from '../../../lib/api/resources'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { useSettingsStore } from '../../../store/settingsStore'
import { resetSolChatSessions } from '../solChatStore'
import { useSolSessionStore } from '../solSessionStore'
import { useFocusStore } from '../../workspace/focusStore'
import { emptySections } from '../../graph/useSolusConfig'
import { fakeSolBridge, installSolBridge, uninstallSolBridge } from '../solWindow.fixtures'
import type { ShellRoute } from '../../workspace/shellStore'
import { SolSidebarHost } from './SolSidebarHost'
import { selectSidebarOpen, SIDEBAR_DEFAULT_WIDTH, useSolSidebarStore } from './solSidebarStore'
import * as events from './sidebarEvents'

vi.mock('../solApi', () => ({
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn().mockResolvedValue([]),
  listSolConversations: vi.fn().mockResolvedValue([]),
  fetchArtifactBlob: vi.fn(),
  streamSolMessage: vi.fn()
}))
vi.mock('../../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/resources')>()),
  classifyQuery: vi.fn(),
  getSolus: vi.fn(),
  updateSolMode: vi.fn().mockResolvedValue({})
}))
vi.mock('./sidebarEvents', () => ({ reportSidebarToggled: vi.fn() }))

const streamSolMessage = vi.mocked(solApi.streamSolMessage)
const report = vi.mocked(events.reportSidebarToggled)
const navigate = vi.fn()

function host(route: ShellRoute = { name: 'workspace' }): ReturnType<typeof render> {
  return render(<SolSidebarHost route={route} navigate={navigate} />)
}

const panel = (): HTMLElement => screen.getByRole('complementary', { name: 'SOL sidebar' })
const open = (): void => act(() => useSolSidebarStore.getState().setOpen(true))
const isOpen = (key = 'workspace'): boolean => selectSidebarOpen(useSolSidebarStore.getState(), key)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  uninstallSolBridge()
  resetSolChatSessions()
  useSolSessionStore.setState({ conversationByProject: {} } as never)
  useSolSidebarStore.getState().reset()
  useFocusStore.getState().reset()
  vi.mocked(solApi.createSolConversation).mockResolvedValue({ id: 'c1' } as solApi.SolConversation)
  vi.mocked(resources.getSolus).mockResolvedValue({ entity_id: 's1', sections: emptySections() })
  useSettingsStore.setState({ solMode: 'Guide' })
  useWorkspaceStore.setState({ teamId: 't1', project: { id: 'p1', name: 'Rover' }, linked: true })
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 })
})

describe('SolSidebarHost — presence', () => {
  it('renders nothing while closed', () => {
    host()
    expect(screen.queryByRole('complementary', { name: 'SOL sidebar' })).toBeNull()
  })

  it('greets with the screen tag, greeting, chips and placeholder', async () => {
    open()
    host()
    const sb = panel()
    expect(within(sb).getByText('WORKSPACE')).toBeInTheDocument()
    expect(await within(sb).findByText(/I can see the workspace graph/)).toBeInTheDocument()
    expect(
      within(sb).getByRole('button', { name: 'Is anything wired inconsistently?' })
    ).toBeVisible()
    expect(within(sb).getByPlaceholderText('Ask about the workspace')).toBeVisible()
  })

  it('names the focused node in the tag on the workspace', () => {
    const id = '00000000-0000-4000-8000-000000000001'
    useFocusStore.setState({
      focusedEntityId: id,
      depth: 1,
      cache: { [`p1:${id}@1`]: { entities: [{ id, name: 'imu' }], relations: [] } as never }
    })
    open()
    host()
    expect(within(panel()).getByText('WORKSPACE · imu')).toBeInTheDocument()
  })

  it('follows the person to the next screen, with that screen\'s copy', () => {
    open()
    const { rerender } = host({ name: 'workspace' })
    rerender(<SolSidebarHost route={{ name: 'bench' }} navigate={navigate} />)
    expect(within(panel()).getByText('LIVE BENCH')).toBeInTheDocument()
    expect(panel()).toHaveAttribute('data-phase', 'open')
  })

  it('hides on the SOL page and comes back on the next screen; ⌘J does nothing there', () => {
    open()
    const { rerender } = host({ name: 'sol' })
    expect(screen.queryByRole('complementary', { name: 'SOL sidebar' })).toBeNull()
    fireEvent.keyDown(window, { key: 'j', metaKey: true, ctrlKey: false })
    fireEvent.keyDown(window, { key: 'j', ctrlKey: true, metaKey: false })
    expect(isOpen('home')).toBe(true)
    rerender(<SolSidebarHost route={{ name: 'home' }} navigate={navigate} />)
    expect(panel()).toBeInTheDocument()
  })
})

describe('SolSidebarHost — controls', () => {
  it('⌘J / Ctrl J toggles it for the current screen', async () => {
    host()
    const mac = navigator.platform.toLowerCase().includes('mac')
    fireEvent.keyDown(window, { key: 'j', metaKey: mac, ctrlKey: !mac })
    expect(isOpen()).toBe(true)
    expect(report).toHaveBeenCalledWith('open', 'workspace', 'shortcut')
    expect(panel()).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'j', metaKey: mac, ctrlKey: !mac })
    expect(isOpen()).toBe(false)
    await waitFor(() =>
      expect(screen.queryByRole('complementary', { name: 'SOL sidebar' })).toBeNull()
    )
  })

  it('closes from the header and from Escape', async () => {
    open()
    host()
    fireEvent.click(within(panel()).getByRole('button', { name: 'Close SOL sidebar' }))
    expect(isOpen()).toBe(false)
    expect(report).toHaveBeenCalledWith('close', 'workspace', 'header')
    open()
    fireEvent.keyDown(panel(), { key: 'Escape' })
    expect(isOpen()).toBe(false)
    expect(report).toHaveBeenLastCalledWith('close', 'workspace', 'escape')
  })

  it('leaves Escape to a popover that consumed it', () => {
    open()
    host()
    const box = within(panel()).getByPlaceholderText('Ask about the workspace')
    box.addEventListener('keydown', (event) => event.preventDefault())
    fireEvent.keyDown(box, { key: 'Escape' })
    expect(isOpen()).toBe(true)
  })

  it('expands to the SOL page and closes here', async () => {
    open()
    host()
    fireEvent.click(within(panel()).getByRole('button', { name: 'Open in the SOL page' }))
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('sol'))
    expect(isOpen()).toBe(false)
    expect(report).toHaveBeenCalledWith('expand', 'workspace', 'header')
  })

  it('pops out to the pill only where the SOL window exists', async () => {
    open()
    const { unmount } = host()
    expect(within(panel()).queryByRole('button', { name: 'Pop out to the pill' })).toBeNull()
    unmount()
    const bridge = fakeSolBridge()
    installSolBridge(bridge)
    host()
    fireEvent.click(within(panel()).getByRole('button', { name: 'Pop out to the pill' }))
    await waitFor(() => expect(bridge.open).toHaveBeenCalled())
    expect(isOpen()).toBe(false)
    expect(report).toHaveBeenCalledWith('pop_out', 'workspace', 'header')
  })

  it('a suggestion chip sends its text on the project chat', async () => {
    streamSolMessage.mockResolvedValue(undefined as never)
    open()
    host()
    const chip = "What does this project's graph cover?"
    fireEvent.click(await within(panel()).findByRole('button', { name: chip }))
    await waitFor(() => expect(streamSolMessage).toHaveBeenCalled())
    expect(streamSolMessage.mock.calls[0][0]).toMatchObject({ content: chip })
  })
})

describe('SolSidebarHost — composer', () => {
  it('is just the input, + and Send — no mode, think-harder, confirm or routing footer', () => {
    open()
    host()
    const sb = panel()
    expect(within(sb).getByRole('button', { name: /send/i })).toBeInTheDocument()
    expect(within(sb).queryByText('Think harder')).toBeNull()
    expect(within(sb).queryByText('Confirm every change')).toBeNull()
    expect(within(sb).queryByText(/auto routing/)).toBeNull()
    expect(within(sb).queryByText('Build')).toBeNull()
    expect(within(sb).queryByText('Guide')).toBeNull()
  })
})

describe('SolSidebarHost — anchors', () => {
  it('a typed send carries the workspace focus, like the page', async () => {
    const id = '00000000-0000-4000-8000-000000000002'
    useFocusStore.setState({ focusedEntityId: id })
    streamSolMessage.mockResolvedValue(undefined as never)
    open()
    host()
    const box = within(panel()).getByPlaceholderText('Ask about the workspace')
    fireEvent.change(box, { target: { value: 'Why two buses?' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    await waitFor(() => expect(streamSolMessage).toHaveBeenCalled())
    expect(streamSolMessage.mock.calls[0][0]).toMatchObject({
      content: 'Why two buses?',
      focus: expect.objectContaining({ entityId: id })
    })
  })
})

describe('SolSidebarHost — width and fit', () => {
  it('resizes from the keyboard within bounds', () => {
    open()
    host()
    const handle = within(panel()).getByRole('separator', { name: 'Resize SOL sidebar' })
    expect(handle).toHaveAttribute('aria-valuenow', String(SIDEBAR_DEFAULT_WIDTH))
    fireEvent.keyDown(handle, { key: 'ArrowLeft' })
    expect(useSolSidebarStore.getState().width).toBe(SIDEBAR_DEFAULT_WIDTH + 16)
    fireEvent.keyDown(handle, { key: 'ArrowRight' })
    fireEvent.keyDown(handle, { key: 'ArrowRight' })
    expect(useSolSidebarStore.getState().width).toBe(SIDEBAR_DEFAULT_WIDTH - 16)
  })

  it('resizes by dragging the left edge', () => {
    open()
    host()
    const handle = within(panel()).getByRole('separator', { name: 'Resize SOL sidebar' })
    fireEvent.pointerDown(handle, { clientX: 1000, pointerId: 1 })
    fireEvent.pointerMove(window, { clientX: 960, pointerId: 1 })
    fireEvent.pointerUp(window, { pointerId: 1 })
    expect(useSolSidebarStore.getState().width).toBe(SIDEBAR_DEFAULT_WIDTH + 40)
  })

  it('docks on wide windows and overlays below 1100px', () => {
    open()
    host()
    expect(panel()).toHaveAttribute('data-fit', 'dock')
    act(() => {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1000 })
      window.dispatchEvent(new Event('resize'))
    })
    expect(panel()).toHaveAttribute('data-fit', 'overlay')
  })
})
